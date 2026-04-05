import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import json
import tempfile
from datetime import datetime
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. قاعدة البيانات ==========
conn = sqlite3.connect("exam.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    questions TEXT,
    answers TEXT
)''')
c.execute('''CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    exam_id INTEGER,
    score INTEGER,
    total INTEGER,
    date TEXT
)''')
conn.commit()

def add_exam(title, questions, answers):
    c.execute("INSERT INTO exams (title, questions, answers) VALUES (?,?,?)", 
              (title, json.dumps(questions), json.dumps(answers)))
    conn.commit()
    return c.lastrowid

def get_exams():
    c.execute("SELECT id, title FROM exams")
    return c.fetchall()

def get_exam_by_id(eid):
    c.execute("SELECT title, questions, answers FROM exams WHERE id=?", (eid,))
    row = c.fetchone()
    if row:
        return {"title": row[0], "questions": json.loads(row[1]), "answers": json.loads(row[2])}
    return None

def save_result(user_id, exam_id, score, total):
    c.execute("INSERT INTO results (user_id, exam_id, score, total, date) VALUES (?,?,?,?,?)",
              (user_id, exam_id, score, total, datetime.now().isoformat()))
    conn.commit()

# ========== 2. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 قائمة الاختبارات", callback_data="list_exams"))
    if message.chat.id == OWNER_ID:
        markup.add(InlineKeyboardButton("➕ إضافة اختبار", callback_data="add_exam"))
    bot.send_message(message.chat.id, "🎓 مرحباً بك في بوت الاختبارات!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "list_exams")
def list_exams(call):
    exams = get_exams()
    if not exams:
        bot.send_message(call.message.chat.id, "لا توجد اختبارات حالياً.")
        return
    markup = InlineKeyboardMarkup()
    for eid, title in exams:
        markup.add(InlineKeyboardButton(title, callback_data=f"exam_{eid}"))
    bot.edit_message_text("📚 اختر الاختبار:", call.message.chat.id, call.message.message_id, reply_markup=markup)

# ========== 3. أداء الاختبار ==========
user_answers = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith("exam_"))
def start_exam(call):
    eid = int(call.data.split("_")[1])
    exam = get_exam_by_id(eid)
    if not exam:
        bot.answer_callback_query(call.id, "الاختبار غير موجود")
        return
    
    user_answers[call.message.chat.id] = {
        "exam_id": eid,
        "questions": exam["questions"],
        "answers": exam["answers"],
        "user_ans": [],
        "index": 0
    }
    bot.answer_callback_query(call.id, f"بدأ الاختبار: {exam['title']}")
    send_question(call.message.chat.id)

def send_question(user_id):
    data = user_answers.get(user_id)
    if not data:
        return
    idx = data["index"]
    if idx >= len(data["questions"]):
        finish_exam(user_id)
        return
    
    q = data["questions"][idx]
    if q["type"] == "mcq":
        markup = InlineKeyboardMarkup()
        for opt in q["options"]:
            markup.add(InlineKeyboardButton(opt, callback_data=f"ans_{opt}"))
        bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}", reply_markup=markup)
    elif q["type"] == "truefalse":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ صح", callback_data="ans_صح"), InlineKeyboardButton("❌ خطأ", callback_data="ans_خطأ"))
        bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}", reply_markup=markup)
    else:
        msg = bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}\nأجب كتابياً:")
        bot.register_next_step_handler(msg, process_essay, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def answer_callback(call):
    user_id = call.message.chat.id
    answer = call.data.split("_")[1]
    data = user_answers.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "انتهت الجلسة")
        return
    data["user_ans"].append(answer)
    data["index"] += 1
    bot.answer_callback_query(call.id)
    bot.delete_message(user_id, call.message.message_id)
    send_question(user_id)

def process_essay(message, user_id):
    answer = message.text.strip()
    data = user_answers.get(user_id)
    if not data:
        return
    data["user_ans"].append(answer)
    data["index"] += 1
    send_question(user_id)

def finish_exam(user_id):
    data = user_answers.pop(user_id, None)
    if not data:
        return
    total = len(data["questions"])
    score = 0
    for i, (q, user_ans, correct) in enumerate(zip(data["questions"], data["user_ans"], data["answers"])):
        if q["type"] == "essay":
            if user_ans.lower().strip() == correct.lower().strip():
                score += 1
        else:
            if user_ans == correct:
                score += 1
    percentage = (score / total) * 100
    save_result(user_id, data["exam_id"], score, total)
    
    # شهادة PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 20, "Certificate", 0, 1, 'C')
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Student ID: {user_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"Score: {score}/{total} ({percentage:.1f}%)", 0, 1, 'C')
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'C')
    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.cell(0, 10, "@zakros_onlinebot", 0, 0, 'C')
    
    path = tempfile.mktemp(suffix='.pdf')
    pdf.output(path)
    
    bot.send_message(user_id, f"🎉 انتهى الاختبار!\nنتيجتك: {score}/{total} ({percentage:.1f}%)")
    with open(path, 'rb') as f:
        bot.send_document(user_id, f, caption="شهادتك", visible_file_name="certificate.pdf")
    os.unlink(path)

# ========== 4. إضافة اختبار (للمالك فقط) ==========
temp_exam = {}

@bot.callback_query_handler(func=lambda call: call.data == "add_exam")
def add_exam_start(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح")
        return
    temp_exam[OWNER_ID] = {"step": "title", "questions": [], "answers": []}
    bot.send_message(OWNER_ID, "أرسل عنوان الاختبار:")
    bot.register_next_step_handler(call.message, process_title)

def process_title(message):
    temp_exam[OWNER_ID]["title"] = message.text.strip()
    temp_exam[OWNER_ID]["step"] = "question"
    bot.send_message(OWNER_ID, "أضف السؤال الأول.\nأرسل السؤال ثم النوع في سطر جديد (text/mcq/truefalse):\nمثال:\nما عاصمة فرنسا؟\ntext")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "question")
def process_question(message):
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        bot.send_message(OWNER_ID, "اكتب السؤال ثم النوع في سطر جديد.")
        return
    q_text = lines[0]
    q_type = lines[1].lower()
    if q_type not in ["text", "mcq", "truefalse"]:
        bot.send_message(OWNER_ID, "النوع غير صالح. اختر: text, mcq, truefalse")
        return
    temp_exam[OWNER_ID]["current_q"] = {"text": q_text, "type": q_type}
    if q_type == "mcq":
        temp_exam[OWNER_ID]["step"] = "mcq_options"
        bot.send_message(OWNER_ID, "أرسل الخيارات مفصولة بفواصل (مثال: باريس, لندن, برلين):")
    elif q_type == "truefalse":
        temp_exam[OWNER_ID]["step"] = "truefalse_answer"
        bot.send_message(OWNER_ID, "أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_exam[OWNER_ID]["step"] = "essay_answer"
        bot.send_message(OWNER_ID, "أرسل الإجابة النموذجية:")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "mcq_options")
def process_mcq_options(message):
    opts = [opt.strip() for opt in message.text.split(',')]
    temp_exam[OWNER_ID]["current_q"]["options"] = opts
    temp_exam[OWNER_ID]["step"] = "mcq_answer"
    bot.send_message(OWNER_ID, f"الخيارات: {', '.join(opts)}\nأرسل الإجابة الصحيحة (نص الخيار بالضبط):")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "mcq_answer")
def process_mcq_answer(message):
    temp_exam[OWNER_ID]["current_q"]["answer"] = message.text.strip()
    save_question(OWNER_ID)
    ask_next(OWNER_ID)

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "truefalse_answer")
def process_truefalse_answer(message):
    ans = message.text.strip()
    if ans not in ["صح", "خطأ"]:
        bot.send_message(OWNER_ID, "أرسل 'صح' أو 'خطأ'")
        return
    temp_exam[OWNER_ID]["current_q"]["answer"] = ans
    save_question(OWNER_ID)
    ask_next(OWNER_ID)

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "essay_answer")
def process_essay_answer(message):
    temp_exam[OWNER_ID]["current_q"]["answer"] = message.text.strip()
    save_question(OWNER_ID)
    ask_next(OWNER_ID)

def save_question(uid):
    q = temp_exam[uid]["current_q"]
    temp_exam[uid]["questions"].append(q)
    temp_exam[uid]["answers"].append(q["answer"])
    del temp_exam[uid]["current_q"]

def ask_next(uid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة سؤال", callback_data="next_q"), InlineKeyboardButton("✅ إنهاء", callback_data="finish_exam"))
    bot.send_message(uid, "تم حفظ السؤال. ماذا تريد؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "next_q")
def next_question(call):
    if call.message.chat.id != OWNER_ID:
        return
    temp_exam[OWNER_ID]["step"] = "question"
    bot.edit_message_text("أضف السؤال التالي (سؤال ثم نوع في سطر جديد):", OWNER_ID, call.message.message_id)
    bot.register_next_step_handler(call.message, process_question)

@bot.callback_query_handler(func=lambda call: call.data == "finish_exam")
def finish_creation(call):
    if call.message.chat.id != OWNER_ID:
        return
    data = temp_exam.pop(OWNER_ID)
    eid = add_exam(data["title"], data["questions"], data["answers"])
    bot.edit_message_text(f"✅ تم إنشاء الاختبار '{data['title']}' بنجاح!\nمعرف الاختبار: {eid}\nعدد الأسئلة: {len(data['questions'])}", OWNER_ID, call.message.message_id)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
