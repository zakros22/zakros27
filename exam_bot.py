import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
import sqlite3
import json
import time
import threading
import tempfile
from datetime import datetime
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. قاعدة البيانات ==========
DB_NAME = "exam_bot.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # الطلاب
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        points INTEGER DEFAULT 2,
        total_shares INTEGER DEFAULT 0
    )''')
    # الاختبارات
    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        questions TEXT,
        answers TEXT,
        created_at TEXT
    )''')
    # محاولات الطلاب
    c.execute('''CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER,
        student_id INTEGER,
        answers TEXT,
        score INTEGER,
        total INTEGER,
        percentage REAL,
        completed_at TEXT
    )''')
    # إحالات
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referred_id INTEGER,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# ========== 2. دوال الطلاب ==========
def get_student(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT points, total_shares FROM students WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO students (user_id, points, total_shares) VALUES (?,?,?)", (user_id, 2, 0))
        conn.commit()
        conn.close()
        return {"points": 2, "total_shares": 0}
    conn.close()
    return {"points": row[0], "total_shares": row[1]}

def update_points(user_id, delta):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()

def add_share(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT total_shares FROM students WHERE user_id=?", (user_id,))
    shares = c.fetchone()[0]
    if shares % 4 == 0:
        c.execute("UPDATE students SET points = points + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_referral(referrer_id, referred_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?,?,?)", (referrer_id, referred_id, datetime.now().isoformat()))
    c.execute("UPDATE students SET points = points + 1 WHERE user_id=?", (referrer_id,))
    conn.commit()
    conn.close()

# ========== 3. إنشاء الاختبارات (للمالك فقط) ==========
temp_exam = {}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    student = get_student(user_id)
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ تم تفعيل الإحالة! +1 نقطة للداعم.")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 دخول إلى اختبار", callback_data="enter_exam"))
    markup.add(InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link"))
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("➕ إنشاء اختبار جديد", callback_data="create_new_exam"))
        markup.add(InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"))
    
    bot.send_message(user_id,
        f"🎓 *بوت الامتحانات*\n\n"
        f"• رصيدك: {student['points']} نقطة\n"
        f"• كل اختبار يستهلك نقطة.\n"
        f"• شارك الرابط لتحصل على نقاط مجانية:\n"
        f"`https://t.me/{bot.get_me().username}?start={user_id}`\n\n"
        f"📌 @zakros_onlinebot",
        parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "share_link")
def share_link(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"🎁 رابط إحالتك:\n`https://t.me/{bot.get_me().username}?start={user_id}`\n\nكل 4 مشاركات = نقطة إضافية.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "enter_exam")
def enter_exam(call):
    user_id = call.message.chat.id
    student = get_student(user_id)
    if student["points"] <= 0:
        bot.answer_callback_query(call.id, "ليس لديك نقاط. شارك الرابط لتحصل على نقاط.", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT exam_id, title FROM exams ORDER BY exam_id DESC")
    exams = c.fetchall()
    conn.close()
    
    if not exams:
        bot.send_message(user_id, "لا توجد اختبارات متاحة حالياً.")
        return
    
    markup = InlineKeyboardMarkup()
    for eid, title in exams:
        markup.add(InlineKeyboardButton(title, callback_data=f"exam_{eid}"))
    bot.send_message(user_id, "📚 اختر الاختبار:", reply_markup=markup)

# ========== 4. أداء الاختبار ==========
user_exam_sessions = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith("exam_"))
def start_exam(call):
    user_id = call.message.chat.id
    exam_id = int(call.data.split("_")[1])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title, questions, answers FROM exams WHERE exam_id=?", (exam_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        bot.answer_callback_query(call.id, "الاختبار غير موجود.", True)
        return
    
    title, questions_json, answers_json = row
    questions = json.loads(questions_json)
    answers = json.loads(answers_json)
    
    update_points(user_id, -1)
    
    user_exam_sessions[user_id] = {
        "exam_id": exam_id,
        "title": title,
        "questions": questions,
        "answers": answers,
        "user_answers": [],
        "current_index": 0
    }
    
    bot.answer_callback_query(call.id, f"بدأ الاختبار: {title}")
    send_question(user_id)

def send_question(user_id):
    session = user_exam_sessions.get(user_id)
    if not session:
        return
    
    idx = session["current_index"]
    if idx >= len(session["questions"]):
        finish_exam(user_id)
        return
    
    q = session["questions"][idx]
    markup = None
    
    if q["type"] == "mcq":
        markup = InlineKeyboardMarkup()
        for opt in q["options"]:
            markup.add(InlineKeyboardButton(opt, callback_data=f"ans_{opt}"))
    elif q["type"] == "truefalse":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ صح", callback_data="ans_صح"), InlineKeyboardButton("❌ خطأ", callback_data="ans_خطأ"))
    else:
        msg = bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}\n\nأجب كتابياً:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_essay, user_id)
        return
    
    bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def process_mcq_answer(call):
    user_id = call.message.chat.id
    answer = call.data.split("_")[1]
    session = user_exam_sessions.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة.", True)
        return
    
    session["user_answers"].append(answer)
    session["current_index"] += 1
    bot.answer_callback_query(call.id)
    bot.delete_message(user_id, call.message.message_id)
    send_question(user_id)

def process_essay(message, user_id):
    answer = message.text.strip()
    session = user_exam_sessions.get(user_id)
    if not session:
        return
    session["user_answers"].append(answer)
    session["current_index"] += 1
    send_question(user_id)

def finish_exam(user_id):
    session = user_exam_sessions.pop(user_id, None)
    if not session:
        return
    
    total = len(session["questions"])
    score = 0
    details = []
    for i, (q, user_ans, correct) in enumerate(zip(session["questions"], session["user_answers"], session["answers"])):
        if q["type"] == "essay":
            is_correct = user_ans.lower().strip() == correct.lower().strip()
        else:
            is_correct = (user_ans == correct)
        score += 1 if is_correct else 0
        details.append(f"س{i+1}: {'✅' if is_correct else '❌'} (الصواب: {correct})")
    
    percentage = (score / total) * 100
    
    # حفظ المحاولة
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO attempts (exam_id, student_id, answers, score, total, percentage, completed_at) VALUES (?,?,?,?,?,?,?)",
              (session["exam_id"], user_id, json.dumps(session["user_answers"]), score, total, percentage, datetime.now().isoformat()))
    attempt_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # شهادة PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 20, "Certificate of Completion", 0, 1, 'C')
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Student ID: {user_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"Exam: {session['title']}", 0, 1, 'C')
    pdf.cell(0, 10, f"Score: {score}/{total} ({percentage:.1f}%)", 0, 1, 'C')
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'C')
    pdf.cell(0, 10, f"Certificate ID: {attempt_id}", 0, 1, 'C')
    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.cell(0, 10, "Verified by @zakros_onlinebot", 0, 0, 'C')
    
    pdf_path = tempfile.mktemp(suffix='.pdf')
    pdf.output(pdf_path)
    
    bot.send_message(user_id, f"🎉 *انتهى الاختبار!*\nالنتيجة: {score}/{total} ({percentage:.1f}%)\n\n" + "\n".join(details[:10]), parse_mode="Markdown")
    with open(pdf_path, 'rb') as f:
        bot.send_document(user_id, f, caption=f"📜 شهادة اختبار {session['title']}\n@zakros_onlinebot", visible_file_name=f"certificate_{attempt_id}.pdf")
    os.unlink(pdf_path)

# ========== 5. إنشاء اختبار (للمالك فقط) ==========
@bot.callback_query_handler(func=lambda call: call.data == "create_new_exam")
def create_exam_start(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    temp_exam[OWNER_ID] = {"step": "title", "questions": [], "answers": []}
    bot.send_message(OWNER_ID, "📌 أرسل عنوان الاختبار:")
    bot.register_next_step_handler(call.message, process_exam_title)

def process_exam_title(message):
    temp_exam[OWNER_ID]["title"] = message.text.strip()
    temp_exam[OWNER_ID]["step"] = "question"
    bot.send_message(OWNER_ID, "➕ أضف السؤال الأول:\n\n(أرسل السؤال، ثم في السطر التالي اكتب نوعه: text / mcq / truefalse)\nمثال:\nما عاصمة فرنسا؟\ntext")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "question")
def process_question(message):
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        bot.send_message(OWNER_ID, "❌ اكتب السؤال ثم النوع في سطر جديد.")
        return
    q_text = lines[0]
    q_type = lines[1].lower()
    if q_type not in ["text", "mcq", "truefalse"]:
        bot.send_message(OWNER_ID, "❌ النوع غير صالح. اختر: text, mcq, truefalse")
        return
    
    temp_exam[OWNER_ID]["current_q"] = {"text": q_text, "type": q_type}
    
    if q_type == "mcq":
        temp_exam[OWNER_ID]["step"] = "mcq_options"
        bot.send_message(OWNER_ID, "📋 أرسل خيارات السؤال مفصولة بفواصل (مثال: باريس, لندن, برلين, مدريد):")
    elif q_type == "truefalse":
        temp_exam[OWNER_ID]["step"] = "truefalse_answer"
        bot.send_message(OWNER_ID, "✅ أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_exam[OWNER_ID]["step"] = "answer"
        bot.send_message(OWNER_ID, "✍️ أرسل الإجابة النموذجية للسؤال:")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "mcq_options")
def process_mcq_options(message):
    options = [opt.strip() for opt in message.text.split(',')]
    temp_exam[OWNER_ID]["current_q"]["options"] = options
    temp_exam[OWNER_ID]["step"] = "mcq_answer"
    bot.send_message(OWNER_ID, f"✅ الخيارات: {', '.join(options)}\nالآن أرسل الإجابة الصحيحة (نص الخيار بالضبط):")

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "mcq_answer")
def process_mcq_answer(message):
    answer = message.text.strip()
    temp_exam[OWNER_ID]["current_q"]["answer"] = answer
    save_current_question(OWNER_ID)
    ask_next(OWNER_ID)

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "truefalse_answer")
def process_truefalse_answer(message):
    answer = message.text.strip()
    if answer not in ["صح", "خطأ"]:
        bot.send_message(OWNER_ID, "❌ أرسل 'صح' أو 'خطأ'")
        return
    temp_exam[OWNER_ID]["current_q"]["answer"] = answer
    save_current_question(OWNER_ID)
    ask_next(OWNER_ID)

@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and temp_exam.get(OWNER_ID, {}).get("step") == "answer")
def process_answer(message):
    answer = message.text.strip()
    temp_exam[OWNER_ID]["current_q"]["answer"] = answer
    save_current_question(OWNER_ID)
    ask_next(OWNER_ID)

def save_current_question(uid):
    q = temp_exam[uid]["current_q"]
    temp_exam[uid]["questions"].append(q)
    temp_exam[uid]["answers"].append(q["answer"])
    del temp_exam[uid]["current_q"]

def ask_next(uid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة سؤال آخر", callback_data="add_another"))
    markup.add(InlineKeyboardButton("✅ إنهاء وإنشاء الاختبار", callback_data="finish_exam_creation"))
    bot.send_message(uid, "✅ تم حفظ السؤال. ماذا تريد أن تفعل؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_another")
def add_another(call):
    if call.message.chat.id != OWNER_ID:
        return
    temp_exam[OWNER_ID]["step"] = "question"
    bot.edit_message_text("➕ أضف السؤال التالي:", OWNER_ID, call.message.message_id)
    bot.register_next_step_handler(call.message, process_question)

@bot.callback_query_handler(func=lambda call: call.data == "finish_exam_creation")
def finish_creation(call):
    if call.message.chat.id != OWNER_ID:
        return
    data = temp_exam.pop(OWNER_ID)
    title = data["title"]
    questions = data["questions"]
    answers = data["answers"]
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO exams (title, questions, answers, created_at) VALUES (?,?,?,?)",
              (title, json.dumps(questions), json.dumps(answers), datetime.now().isoformat()))
    conn.commit()
    exam_id = c.lastrowid
    conn.close()
    
    bot.edit_message_text(f"✅ تم إنشاء الاختبار '{title}' بنجاح!\nمعرف الاختبار: {exam_id}\nعدد الأسئلة: {len(questions)}", OWNER_ID, call.message.message_id)

# ========== 6. إحصائيات المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students")
    students_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM exams")
    exams_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM attempts")
    attempts_count = c.fetchone()[0]
    conn.close()
    bot.send_message(OWNER_ID, f"📊 *إحصائيات البوت*\n👥 عدد الطلاب: {students_count}\n📚 عدد الاختبارات: {exams_count}\n📝 عدد المحاولات: {attempts_count}", parse_mode="Markdown")

if __name__ == "__main__":
    print("✅ بوت الامتحانات يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
