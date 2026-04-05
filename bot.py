import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import json
import tempfile
import string
import random
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
# الاختبارات
c.execute('''CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    questions TEXT,
    answers TEXT,
    link_code TEXT UNIQUE,
    created_by INTEGER
)''')
# الطلاب
c.execute('''CREATE TABLE IF NOT EXISTS students (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    points INTEGER DEFAULT 2,
    total_shares INTEGER DEFAULT 0
)''')
# نتائج الطلاب
c.execute('''CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER,
    student_id INTEGER,
    score INTEGER,
    total INTEGER,
    percentage REAL,
    date TEXT
)''')
# إحالات
c.execute('''CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER,
    date TEXT
)''')
conn.commit()

def add_exam(title, questions, answers, created_by):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    c.execute("INSERT INTO exams (title, questions, answers, link_code, created_by) VALUES (?,?,?,?,?)",
              (title, json.dumps(questions), json.dumps(answers), code, created_by))
    conn.commit()
    return c.lastrowid, code

def get_exam_by_code(code):
    c.execute("SELECT id, title, questions, answers, created_by FROM exams WHERE link_code=?", (code,))
    row = c.fetchone()
    if row:
        return {"id": row[0], "title": row[1], "questions": json.loads(row[2]), "answers": json.loads(row[3]), "created_by": row[4]}
    return None

def get_exams_by_teacher(teacher_id):
    c.execute("SELECT id, title, link_code FROM exams WHERE created_by=?", (teacher_id,))
    return c.fetchall()

def save_result(exam_id, student_id, score, total, percentage):
    c.execute("INSERT INTO results (exam_id, student_id, score, total, percentage, date) VALUES (?,?,?,?,?,?)",
              (exam_id, student_id, score, total, percentage, datetime.now().isoformat()))
    conn.commit()

def get_results_by_exam(exam_id):
    c.execute("SELECT student_id, score, total, percentage FROM results WHERE exam_id=?", (exam_id,))
    return c.fetchall()

def get_student(user_id):
    c.execute("SELECT points, total_shares FROM students WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO students (user_id, points, total_shares) VALUES (?,?,?)", (user_id, 2, 0))
        conn.commit()
        return {"points": 2, "total_shares": 0}
    return {"points": row[0], "total_shares": row[1]}

def update_points(user_id, delta):
    c.execute("UPDATE students SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()

def add_share(user_id):
    c.execute("UPDATE students SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT total_shares FROM students WHERE user_id=?", (user_id,))
    shares = c.fetchone()[0]
    if shares % 4 == 0:
        c.execute("UPDATE students SET points = points + 1 WHERE user_id=?", (user_id,))
    conn.commit()

def add_referral(referrer_id, referred_id):
    c.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?,?,?)", (referrer_id, referred_id, datetime.now().isoformat()))
    c.execute("UPDATE students SET points = points + 1 WHERE user_id=?", (referrer_id,))
    conn.commit()

# ========== 2. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    student = get_student(user_id)
    # معالجة الإحالة
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ تم تفعيل الإحالة! +1 نقطة للداعم.")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 دخول إلى اختبار", callback_data="enter_exam"))
    markup.add(InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link"))
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("🔧 لوحة التحكم", callback_data="admin_panel"))
        markup.add(InlineKeyboardButton("➕ إنشاء اختبار", callback_data="create_exam"))
    
    bot.send_message(user_id,
        f"🎓 *بوت الاختبارات*\n\n"
        f"• رصيدك: {student['points']} نقطة\n"
        f"• كل اختبار يستهلك نقطة.\n"
        f"• احصل على نقاط مجانية عبر مشاركة الرابط (كل 4 مشاركات = نقطة).\n"
        f"رابط إحالتك:\n`https://t.me/{bot.get_me().username}?start={user_id}`\n\n"
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
    
    bot.send_message(user_id, "🔗 أرسل رمز الاختبار (مثال: ABC123):")
    bot.register_next_step_handler(call.message, process_exam_code)

def process_exam_code(message):
    user_id = message.chat.id
    code = message.text.strip().upper()
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(user_id, "❌ رمز الاختبار غير صحيح.")
        return
    
    update_points(user_id, -1)
    start_exam(user_id, exam)

def start_exam(user_id, exam):
    user_answers[user_id] = {
        "exam_id": exam["id"],
        "title": exam["title"],
        "questions": exam["questions"],
        "answers": exam["answers"],
        "user_ans": [],
        "index": 0
    }
    send_question(user_id)

# تخزين مؤقت للإجابات
user_answers = {}

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
        bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}", parse_mode="Markdown", reply_markup=markup)
    elif q["type"] == "truefalse":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ صح", callback_data="ans_صح"), InlineKeyboardButton("❌ خطأ", callback_data="ans_خطأ"))
        bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}", parse_mode="Markdown", reply_markup=markup)
    else:
        msg = bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}\n\nأجب كتابياً:", parse_mode="Markdown")
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
    save_result(data["exam_id"], user_id, score, total, percentage)
    
    # شهادة PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 20, "Certificate", 0, 1, 'C')
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Student ID: {user_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"Exam: {data['title']}", 0, 1, 'C')
    pdf.cell(0, 10, f"Score: {score}/{total} ({percentage:.1f}%)", 0, 1, 'C')
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'C')
    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.cell(0, 10, "@zakros_onlinebot", 0, 0, 'C')
    
    path = tempfile.mktemp(suffix='.pdf')
    pdf.output(path)
    
    bot.send_message(user_id, f"🎉 *انتهى الاختبار!*\nنتيجتك: {score}/{total} ({percentage:.1f}%)", parse_mode="Markdown")
    with open(path, 'rb') as f:
        bot.send_document(user_id, f, caption="📜 شهادتك", visible_file_name="certificate.pdf")
    os.unlink(path)

# ========== 3. إنشاء اختبار (للمالك فقط) ==========
temp_exam = {}

@bot.callback_query_handler(func=lambda call: call.data == "create_exam")
def create_exam_start(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح")
        return
    temp_exam[OWNER_ID] = {"step": "title", "questions": [], "answers": []}
    bot.send_message(OWNER_ID, "📌 أرسل عنوان الاختبار:")
    bot.register_next_step_handler(call.message, process_title)

def process_title(message):
    temp_exam[OWNER_ID]["title"] = message.text.strip()
    temp_exam[OWNER_ID]["step"] = "question"
    bot.send_message(OWNER_ID, "➕ أضف السؤال الأول.\nأرسل السؤال ثم النوع في سطر جديد (mcq/truefalse/text):\nمثال:\nما عاصمة فرنسا؟\ntext")

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
        bot.send_message(OWNER_ID, "📋 أرسل الخيارات مفصولة بفواصل (مثال: باريس, لندن, برلين):")
    elif q_type == "truefalse":
        temp_exam[OWNER_ID]["step"] = "truefalse_answer"
        bot.send_message(OWNER_ID, "✅ أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_exam[OWNER_ID]["step"] = "essay_answer"
        bot.send_message(OWNER_ID, "✍️ أرسل الإجابة النموذجية:")

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
        bot.send_message(OWNER_ID, "❌ أرسل 'صح' أو 'خطأ'")
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
    bot.send_message(uid, "✅ تم حفظ السؤال. ماذا تريد؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "next_q")
def next_question(call):
    if call.message.chat.id != OWNER_ID:
        return
    temp_exam[OWNER_ID]["step"] = "question"
    bot.edit_message_text("➕ أضف السؤال التالي (سؤال ثم نوع في سطر جديد):", OWNER_ID, call.message.message_id)
    bot.register_next_step_handler(call.message, process_question)

@bot.callback_query_handler(func=lambda call: call.data == "finish_exam")
def finish_creation(call):
    if call.message.chat.id != OWNER_ID:
        return
    data = temp_exam.pop(OWNER_ID)
    eid, code = add_exam(data["title"], data["questions"], data["answers"], OWNER_ID)
    bot.edit_message_text(f"✅ تم إنشاء الاختبار '{data['title']}' بنجاح!\n\n🔗 رابط الاختبار:\n`https://t.me/{bot.get_me().username}?start=exam_{code}`\n\nرمز الاختبار: `{code}`\nعدد الأسئلة: {len(data['questions'])}", OWNER_ID, call.message.message_id, parse_mode="Markdown")

# ========== 4. لوحة تحكم المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط لمستخدم", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("➖ خصم نقاط من مستخدم", callback_data="admin_remove_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("📋 قائمة الاختبارات", callback_data="admin_exams"))
    markup.add(InlineKeyboardButton("📈 نتائج اختبار", callback_data="admin_results"))
    bot.send_message(OWNER_ID, "🔧 *لوحة تحكم المالك*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_points")
def admin_add_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط (مثال: 123456789 5):")
    bot.register_next_step_handler(msg, add_points_step)

def add_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ تم إضافة {pts} نقطة للمستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة. أرسل: user_id points")

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_points")
def admin_remove_points(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط (مثال: 123456789 3):")
    bot.register_next_step_handler(msg, remove_points_step)

def remove_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, -pts)
        bot.send_message(OWNER_ID, f"✅ تم خصم {pts} نقطة من المستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.message.chat.id != OWNER_ID:
        return
    c.execute("SELECT COUNT(*) FROM students")
    students = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM exams")
    exams = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM results")
    results = c.fetchone()[0]
    c.execute("SELECT SUM(points) FROM students")
    total_points = c.fetchone()[0] or 0
    bot.send_message(OWNER_ID, f"📊 *إحصائيات البوت*\n👥 الطلاب: {students}\n📚 الاختبارات: {exams}\n📝 المحاولات: {results}\n⭐ مجموع النقاط: {total_points}", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "admin_exams")
def admin_exams(call):
    if call.message.chat.id != OWNER_ID:
        return
    exams = get_exams_by_teacher(OWNER_ID)
    if not exams:
        bot.send_message(OWNER_ID, "لا توجد اختبارات.")
        return
    txt = "📋 *قائمة الاختبارات*\n"
    for eid, title, code in exams:
        txt += f"• {title}\n   رمز: `{code}`\n   رابط: https://t.me/{bot.get_me().username}?start=exam_{code}\n\n"
    bot.send_message(OWNER_ID, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "admin_results")
def admin_results(call):
    if call.message.chat.id != OWNER_ID:
        return
    msg = bot.send_message(OWNER_ID, "أرسل رمز الاختبار (مثال: ABC123):")
    bot.register_next_step_handler(msg, show_results)

def show_results(message):
    code = message.text.strip().upper()
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(OWNER_ID, "❌ رمز غير صحيح.")
        return
    results = get_results_by_exam(exam["id"])
    if not results:
        bot.send_message(OWNER_ID, f"لا توجد نتائج لاختبار {exam['title']}.")
        return
    txt = f"📈 *نتائج اختبار {exam['title']}*\n\n"
    for sid, score, total, pct in results:
        txt += f"👤 مستخدم {sid}: {score}/{total} ({pct:.1f}%)\n"
    bot.send_message(OWNER_ID, txt, parse_mode="Markdown")

# معالجة الروابط المباشرة للاختبارات
@bot.message_handler(func=lambda m: m.text and m.text.startswith("https://t.me/") and "start=exam_" in m.text)
def handle_exam_link(message):
    code = message.text.split("start=exam_")[1].split()[0]
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(message.chat.id, "❌ رابط غير صحيح.")
        return
    student = get_student(message.chat.id)
    if student["points"] <= 0:
        bot.send_message(message.chat.id, "❌ ليس لديك نقاط كافية. شارك الرابط لتحصل على نقاط.")
        return
    update_points(message.chat.id, -1)
    start_exam(message.chat.id, exam)

if __name__ == "__main__":
    print("✅ بوت الاختبارات يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
