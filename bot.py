import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
import sqlite3
import json
import random
import string
import time
import threading
from datetime import datetime, timedelta
import tempfile
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
        name TEXT,
        points INTEGER DEFAULT 2,
        total_shares INTEGER DEFAULT 0
    )''')
    # المعلمون (يمكن إضافة معلمين جدد عبر المالك)
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        user_id INTEGER PRIMARY KEY,
        name TEXT
    )''')
    # إضافة المالك كمعلم افتراضي
    c.execute("INSERT OR IGNORE INTO teachers (user_id, name) VALUES (?, ?)", (OWNER_ID, "المالك"))
    # الاختبارات
    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        exam_id TEXT PRIMARY KEY,
        teacher_id INTEGER,
        title TEXT,
        duration_minutes INTEGER,
        created_at TEXT,
        questions TEXT,
        answers TEXT,
        active INTEGER DEFAULT 1
    )''')
    # محاولات الطلاب
    c.execute('''CREATE TABLE IF NOT EXISTS attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id TEXT,
        student_id INTEGER,
        answers TEXT,
        score INTEGER,
        percentage REAL,
        completed_at TEXT,
        certificate TEXT
    )''')
    # إحالات (لمشاركة الرابط)
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referred_id INTEGER,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# ========== 2. دوال مساعدة ==========
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
    c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?,?,?)", 
              (referrer_id, referred_id, datetime.now().isoformat()))
    c.execute("UPDATE students SET points = points + 1 WHERE user_id=?", (referrer_id,))
    conn.commit()
    conn.close()

# ========== 3. إنشاء الاختبارات ==========
# تخزين مؤقت لبيانات الاختبار أثناء الإنشاء
temp_exams = {}

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    student = get_student(user_id)
    # معالجة الإحالة إذا وجدت
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ تم تفعيل الإحالة! حصل الداعم على نقطة.")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 دخول إلى اختبار", callback_data="enter_exam"))
    markup.add(InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link"))
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("🔧 لوحة التحكم", callback_data="admin_panel"))
        markup.add(InlineKeyboardButton("➕ إنشاء اختبار جديد", callback_data="create_new_exam"))
    
    bot.send_message(user_id,
        f"🎓 *بوت الامتحانات*\n\n"
        f"• رصيدك: {student['points']} نقطة\n"
        f"• كل محاولة اختبار تستهلك نقطة واحدة.\n"
        f"• احصل على نقاط مجانية عبر مشاركة الرابط (كل 4 مشاركات = نقطة).\n"
        f"رابط إحالتك:\n`https://t.me/{bot.get_me().username}?start={user_id}`\n\n"
        f"📌 البوت: @zakros_onlinebot",
        parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "share_link")
def share_link(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"🎁 شارك هذا الرابط مع أصدقائك:\n`https://t.me/{bot.get_me().username}?start={user_id}`\n\nكل 4 مشاركات تمنحك نقطة إضافية.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "enter_exam")
def enter_exam(call):
    user_id = call.message.chat.id
    student = get_student(user_id)
    if student["points"] <= 0:
        bot.answer_callback_query(call.id, "ليس لديك نقاط كافية. شارك الرابط لتحصل على نقاط مجانية.", show_alert=True)
        return
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT exam_id, title FROM exams WHERE active=1")
    exams = c.fetchall()
    conn.close()
    
    if not exams:
        bot.send_message(user_id, "لا توجد اختبارات متاحة حالياً.")
        return
    
    markup = InlineKeyboardMarkup()
    for exam_id, title in exams:
        markup.add(InlineKeyboardButton(title, callback_data=f"start_exam_{exam_id}"))
    bot.send_message(user_id, "📚 اختر الاختبار:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_exam_"))
def start_exam(call):
    user_id = call.message.chat.id
    exam_id = call.data.split("_")[2]
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title, duration_minutes, questions, answers FROM exams WHERE exam_id=?", (exam_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        bot.answer_callback_query(call.id, "الاختبار غير موجود.", True)
        return
    
    title, duration, questions_json, answers_json = row
    questions = json.loads(questions_json)
    
    # استهلاك نقطة
    update_points(user_id, -1)
    
    # تخزين جلسة الاختبار
    temp_exams[user_id] = {
        "exam_id": exam_id,
        "title": title,
        "questions": questions,
        "answers": json.loads(answers_json),
        "user_answers": [],
        "start_time": time.time(),
        "duration": duration
    }
    
    bot.answer_callback_query(call.id, f"بدأ الاختبار: {title}\nالوقت المتاح: {duration} دقيقة", show_alert=True)
    send_next_question(user_id)

def send_next_question(user_id):
    session = temp_exams.get(user_id)
    if not session:
        return
    
    idx = len(session["user_answers"])
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
        # سؤال مقالي - سيتم إرسال رسالة عادية
        msg = bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}\n\nأجب كتابياً:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_essay_answer, user_id, idx)
        return
    
    bot.send_message(user_id, f"📝 *السؤال {idx+1}:*\n{q['text']}", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def process_answer(call):
    user_id = call.message.chat.id
    answer = call.data.split("_")[1]
    session = temp_exams.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة.", True)
        return
    
    idx = len(session["user_answers"])
    session["user_answers"].append(answer)
    bot.answer_callback_query(call.id)
    bot.delete_message(user_id, call.message.message_id)
    send_next_question(user_id)

def process_essay_answer(message, user_id, idx):
    answer = message.text.strip()
    session = temp_exams.get(user_id)
    if not session:
        return
    session["user_answers"].append(answer)
    send_next_question(user_id)

def finish_exam(user_id):
    session = temp_exams.pop(user_id, None)
    if not session:
        return
    
    # تصحيح الاختبار
    score = 0
    total = len(session["questions"])
    results = []
    for i, (q, user_ans, correct) in enumerate(zip(session["questions"], session["user_answers"], session["answers"])):
        if q["type"] == "essay":
            # تقييم المقالي (مقارنة بسيطة)
            is_correct = user_ans.lower().strip() == correct.lower().strip()
            score += 1 if is_correct else 0
            results.append(f"س{i+1}: {'✅' if is_correct else '❌'} (جوابك: {user_ans[:50]})")
        else:
            is_correct = user_ans == correct
            score += 1 if is_correct else 0
            results.append(f"س{i+1}: {'✅' if is_correct else '❌'} (الصواب: {correct})")
    
    percentage = (score / total) * 100
    
    # حفظ المحاولة
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO attempts (exam_id, student_id, answers, score, percentage, completed_at) VALUES (?,?,?,?,?,?)",
              (session["exam_id"], user_id, json.dumps(session["user_answers"]), score, percentage, datetime.now().isoformat()))
    attempt_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # إنشاء شهادة PDF
    pdf_path = create_certificate(user_id, session["title"], score, total, percentage, attempt_id)
    
    # إرسال النتيجة
    bot.send_message(user_id, f"🎉 *انتهى الاختبار!*\n\nالنتيجة: {score}/{total}\nالنسبة: {percentage:.1f}%\n\n" + "\n".join(results[:5]), parse_mode="Markdown")
    
    with open(pdf_path, 'rb') as f:
        bot.send_document(user_id, f, caption=f"📜 شهادتك في اختبار {session['title']}\n@zakros_onlinebot", visible_file_name=f"certificate_{session['exam_id']}_{attempt_id}.pdf")
    os.unlink(pdf_path)

def create_certificate(user_id, title, score, total, percentage, attempt_id):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 20, "Certificate of Completion", 0, 1, 'C')
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"This certificate is awarded to Student ID: {user_id}", 0, 1, 'C')
    pdf.cell(0, 10, f"For successfully completing the exam: {title}", 0, 1, 'C')
    pdf.cell(0, 10, f"Score: {score}/{total} ({percentage:.1f}%)", 0, 1, 'C')
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'C')
    pdf.cell(0, 10, f"Certificate ID: {attempt_id}", 0, 1, 'C')
    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.cell(0, 10, "Verified by @zakros_onlinebot", 0, 0, 'C')
    path = tempfile.mktemp(suffix='.pdf')
    pdf.output(path)
    return path

# ========== 4. إنشاء اختبار (للمعلم/المالك) ==========
temp_creation = {}

@bot.callback_query_handler(func=lambda call: call.data == "create_new_exam")
def create_new_exam(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    temp_creation[call.message.chat.id] = {"step": "title", "questions": []}
    bot.send_message(call.message.chat.id, "📌 أرسل عنوان الاختبار:")
    bot.register_next_step_handler(call.message, process_title)

def process_title(message):
    user_id = message.chat.id
    temp_creation[user_id]["title"] = message.text.strip()
    temp_creation[user_id]["step"] = "duration"
    bot.send_message(user_id, "⏱️ أرسل مدة الاختبار بالدقائق (مثال: 30):")

def process_duration(message):
    user_id = message.chat.id
    try:
        duration = int(message.text.strip())
        temp_creation[user_id]["duration"] = duration
        temp_creation[user_id]["step"] = "question_text"
        bot.send_message(user_id, "📝 أضف السؤال الأول:\n\nاكتب السؤال، ثم في السطر التالي اكتب نوعه (mcq/truefalse/essay):")
    except:
        bot.send_message(user_id, "❌ أرسل رقماً صحيحاً للمدة.")
        bot.register_next_step_handler(message, process_duration)

@bot.message_handler(func=lambda m: m.chat.id in temp_creation and temp_creation[m.chat.id].get("step") == "question_text")
def process_question(message):
    user_id = message.chat.id
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        bot.send_message(user_id, "❌ اكتب السؤال ثم نوعه في سطر جديد.")
        return
    text = lines[0]
    q_type = lines[1].lower()
    if q_type not in ["mcq", "truefalse", "essay"]:
        bot.send_message(user_id, "❌ النوع غير صالح. اختر: mcq, truefalse, essay")
        return
    
    temp_creation[user_id]["current_question"] = {"text": text, "type": q_type}
    if q_type == "mcq":
        temp_creation[user_id]["step"] = "mcq_options"
        bot.send_message(user_id, "📋 أرسل خيارات السؤال مفصولة بفواصل (مثال: خيار1, خيار2, خيار3):")
    elif q_type == "truefalse":
        temp_creation[user_id]["step"] = "truefalse_answer"
        bot.send_message(user_id, "✅ أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_creation[user_id]["step"] = "essay_answer"
        bot.send_message(user_id, "✍️ أرسل الإجابة النموذجية للسؤال المقالي:")

# ... (متابعة إضافة الأسئلة وحفظ الاختبار)
# (لضيق المساحة، سأكمل في الرد التالي)

if __name__ == "__main__":
    print("✅ بوت الامتحانات يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
