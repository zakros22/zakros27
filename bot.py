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
import difflib
import re
import requests
import arabic_reshaper
from bidi.algorithm import get_display

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. تحميل خط يدعم اللغة العربية ==========
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf"
FONT_PATH = "NotoSansArabic-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
    except:
        FONT_PATH = None

def reshape_arabic(text):
    if any('\u0600' <= c <= '\u06FF' for c in text):
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    return text

# ========== 2. قاعدة البيانات ==========
conn = sqlite3.connect("exam.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    questions TEXT,
    answers TEXT,
    link_code TEXT UNIQUE,
    created_by INTEGER,
    created_at TEXT
)''')
c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    points REAL DEFAULT 2,
    total_shares INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER,
    student_id INTEGER,
    score REAL,
    total REAL,
    percentage REAL,
    details TEXT,
    date TEXT
)''')
c.execute('''CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER,
    date TEXT
)''')
conn.commit()

def add_exam(title, questions, answers, created_by):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    c.execute("INSERT INTO exams (title, questions, answers, link_code, created_by, created_at) VALUES (?,?,?,?,?,?)",
              (title, json.dumps(questions), json.dumps(answers), code, created_by, datetime.now().isoformat()))
    conn.commit()
    return c.lastrowid, code

def get_exam_by_code(code):
    c.execute("SELECT id, title, questions, answers, created_by FROM exams WHERE link_code=?", (code,))
    row = c.fetchone()
    if row:
        return {"id": row[0], "title": row[1], "questions": json.loads(row[2]), "answers": json.loads(row[3]), "created_by": row[4]}
    return None

def get_exams_by_user(user_id):
    c.execute("SELECT id, title, link_code, created_at FROM exams WHERE created_by=? ORDER BY created_at DESC", (user_id,))
    return c.fetchall()

def get_all_exams_by_teacher(teacher_id):
    c.execute("SELECT id, title, link_code, created_at FROM exams WHERE created_by=? ORDER BY created_at DESC", (teacher_id,))
    return c.fetchall()

def save_result(exam_id, student_id, score, total, percentage, details):
    c.execute("INSERT INTO results (exam_id, student_id, score, total, percentage, details, date) VALUES (?,?,?,?,?,?,?)",
              (exam_id, student_id, score, total, percentage, json.dumps(details), datetime.now().isoformat()))
    conn.commit()

def get_results_by_exam(exam_id):
    c.execute("SELECT student_id, score, total, percentage FROM results WHERE exam_id=?", (exam_id,))
    return c.fetchall()

def get_user(user_id):
    c.execute("SELECT points, total_shares FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        # كل مستخدم جديد يبدأ بنقطتين مجانيتين
        c.execute("INSERT INTO users (user_id, points, total_shares) VALUES (?,?,?)", (user_id, 2, 0))
        conn.commit()
        return {"points": 2, "total_shares": 0}
    return {"points": row[0], "total_shares": row[1]}

def update_points(user_id, delta):
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()

def add_share(user_id):
    c.execute("UPDATE users SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT total_shares FROM users WHERE user_id=?", (user_id,))
    shares = c.fetchone()[0]
    points_from_shares = shares * 0.25
    c.execute("UPDATE users SET points = ? WHERE user_id=?", (points_from_shares, user_id))
    conn.commit()

def add_referral(referrer_id, referred_id):
    c.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?,?,?)", (referrer_id, referred_id, datetime.now().isoformat()))
    update_points(referrer_id, 0.25)
    conn.commit()

def calculate_essay_score(user_answer, correct_answer):
    user_clean = user_answer.lower().strip()
    correct_clean = correct_answer.lower().strip()
    
    if user_clean == correct_clean:
        return 1.0, 100.0
    
    user_words = set(re.findall(r'\w+', user_clean))
    correct_words = set(re.findall(r'\w+', correct_clean))
    if correct_words:
        word_match = len(user_words.intersection(correct_words)) / len(correct_words)
    else:
        word_match = 0
    
    char_match = difflib.SequenceMatcher(None, user_clean, correct_clean).ratio()
    final_ratio = (word_match * 0.7) + (char_match * 0.3)
    final_percentage = round(final_ratio * 100, 1)
    
    return round(final_ratio, 2), final_percentage

def get_grade_message(percentage):
    if percentage >= 90:
        return ("ممتاز! 🏆", "أداء رائع، أنت متميز!", (0, 100, 0))
    elif percentage >= 75:
        return ("جيد جدا! 👍", "عمل ممتاز، واصل التميز!", (0, 100, 0))
    elif percentage >= 60:
        return ("جيد! 📚", "نتيجة جيدة، يمكنك التحسين!", (255, 165, 0))
    elif percentage >= 50:
        return ("مقبول! 📖", "تحتاج إلى مذاكرة أكثر قليلا", (255, 165, 0))
    else:
        return ("حظ أوفر! 💪", "لا تيأس، حاول مرة أخرى بعد المذاكرة", (255, 0, 0))

def generate_certificate(user_id, exam_title, score, total, percentage):
    pdf = FPDF()
    pdf.add_page()
    
    if FONT_PATH and os.path.exists(FONT_PATH):
        pdf.add_font('Noto', '', FONT_PATH, uni=True)
        pdf.set_font('Noto', '', 20)
    else:
        pdf.set_font("Helvetica", "", 20)
    
    # عنوان الشهادة
    pdf.set_text_color(0, 51, 102)
    title_text = reshape_arabic("شهادة إتمام الاختبار")
    pdf.cell(0, 25, title_text, 0, 1, 'C')
    pdf.ln(5)
    
    # خط فاصل
    pdf.set_draw_color(0, 102, 204)
    pdf.line(30, 45, 180, 45)
    
    # معلومات الطالب والاختبار
    if FONT_PATH:
        pdf.set_font('Noto', '', 12)
    else:
        pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    
    student_text = reshape_arabic(f"الطالب/الطالبة رقم: {user_id}")
    pdf.cell(0, 12, student_text, 0, 1, 'C')
    
    exam_text = reshape_arabic(f"الاختبار: {exam_title}")
    pdf.cell(0, 12, exam_text, 0, 1, 'C')
    
    date_text = reshape_arabic(f"التاريخ: {datetime.now().strftime('%Y/%m/%d')}")
    pdf.cell(0, 12, date_text, 0, 1, 'C')
    pdf.ln(8)
    
    # مربع النتيجة
    grade_msg, advice, color = get_grade_message(percentage)
    
    pdf.set_fill_color(240, 248, 255)
    pdf.rect(40, 105, 130, 50, 'F')
    pdf.set_draw_color(0, 102, 204)
    pdf.rect(40, 105, 130, 50)
    
    if FONT_PATH:
        pdf.set_font('Noto', '', 16)
    else:
        pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(color[0], color[1], color[2])
    pdf.set_xy(45, 112)
    pdf.cell(120, 12, f"{score:.1f} / {total}", 0, 1, 'C')
    
    if FONT_PATH:
        pdf.set_font('Noto', '', 12)
    else:
        pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(45, 128)
    pdf.cell(120, 12, f"({percentage:.1f}%)", 0, 1, 'C')
    
    pdf.ln(20)
    
    if FONT_PATH:
        pdf.set_font('Noto', '', 14)
    else:
        pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(color[0], color[1], color[2])
    grade_text = reshape_arabic(grade_msg)
    pdf.cell(0, 12, grade_text, 0, 1, 'C')
    
    if FONT_PATH:
        pdf.set_font('Noto', '', 10)
    else:
        pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    advice_text = reshape_arabic(advice)
    pdf.cell(0, 10, advice_text, 0, 1, 'C')
    pdf.ln(10)
    
    # مربع حقوق البوت @ZeQuiz_Bot
    pdf.set_fill_color(230, 240, 255)
    pdf.rect(50, 230, 110, 25, 'F')
    pdf.set_draw_color(0, 102, 204)
    pdf.rect(50, 230, 110, 25)
    
    if FONT_PATH:
        pdf.set_font('Noto', '', 11)
    else:
        pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 51, 102)
    pdf.set_xy(55, 238)
    bot_text = reshape_arabic("@ZeQuiz_Bot")
    pdf.cell(100, 10, bot_text, 0, 1, 'C')
    
    path = tempfile.mktemp(suffix='.pdf')
    pdf.output(path)
    return path

# ========== 3. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    user = get_user(user_id)
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, f"✅ تم تفعيل الإحالة! حصل الداعم على 0.25 نقطة.")
            bot.send_message(int(ref), f"🎉 قام مستخدم جديد بالتسجيل عبر رابطك! تم إضافة 0.25 نقطة إلى رصيدك.")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📝 دخول إلى اختبار", callback_data="enter_exam"))
    markup.add(InlineKeyboardButton("📋 اختباراتي", callback_data="my_exams"))
    markup.add(InlineKeyboardButton("➕ إنشاء اختبار", callback_data="create_exam"))
    markup.add(InlineKeyboardButton("🎁 مشاركة الرابط", callback_data="share_link"))
    if user_id == OWNER_ID:
        markup.add(InlineKeyboardButton("🔧 لوحة التحكم", callback_data="admin_panel"))
    
    bot.send_message(user_id,
        f"🎓 بوت الاختبارات\n\n"
        f"• رصيدك: {user['points']:.2f} نقطة\n"
        f"• إنشاء اختبار جديد يستهلك نقطة واحدة.\n"
        f"• دخول الاختبار مجاني.\n"
        f"• احصل على نقاط عبر مشاركة الرابط (كل مشاركة = 0.25 نقطة).\n"
        f"رابط إحالتك:\nhttps://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 @ZeQuiz_Bot",
        reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "share_link")
def share_link(call):
    user_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"🎁 رابط إحالتك:\nhttps://t.me/{bot.get_me().username}?start={user_id}\n\nكل مشاركة = 0.25 نقطة!")

@bot.callback_query_handler(func=lambda call: call.data == "my_exams")
def my_exams(call):
    user_id = call.message.chat.id
    exams = get_exams_by_user(user_id)
    if not exams:
        bot.send_message(user_id, "📭 لم تقم بإنشاء أي اختبارات بعد.")
        return
    txt = "📋 قائمة الاختبارات التي أنشأتها:\n\n"
    for eid, title, code, created_at in exams:
        txt += f"• {title}\n   رمز: {code}\n   تاريخ: {created_at[:19]}\n   رابط: https://t.me/{bot.get_me().username}?start=exam_{code}\n\n"
    bot.send_message(user_id, txt)

@bot.callback_query_handler(func=lambda call: call.data == "enter_exam")
def enter_exam(call):
    user_id = call.message.chat.id
    bot.send_message(user_id, "🔗 أرسل رمز الاختبار (مثال: ABC123):")
    bot.register_next_step_handler(call.message, process_exam_code)

def process_exam_code(message):
    user_id = message.chat.id
    code = message.text.strip().upper()
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(user_id, "❌ رمز الاختبار غير صحيح.")
        return
    
    start_exam(user_id, exam)

def start_exam(user_id, exam):
    user_answers[user_id] = {
        "exam_id": exam["id"],
        "title": exam["title"],
        "questions": exam["questions"],
        "answers": exam["answers"],
        "user_ans": [],
        "scores": [],
        "index": 0
    }
    send_question(user_id)

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
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for opt in q["options"]:
            buttons.append(InlineKeyboardButton(opt, callback_data=f"ans_{opt}"))
        markup.add(*buttons)
        bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}", reply_markup=markup)
    elif q["type"] == "truefalse":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ صح", callback_data="ans_صح"), InlineKeyboardButton("❌ خطأ", callback_data="ans_خطأ"))
        bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}", reply_markup=markup)
    else:
        msg = bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}\n\nأجب كتابياً:")
        bot.register_next_step_handler(msg, process_essay, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def answer_callback(call):
    user_id = call.message.chat.id
    answer = call.data.split("_")[1]
    data = user_answers.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "انتهت الجلسة")
        return
    
    idx = data["index"]
    q = data["questions"][idx]
    correct = data["answers"][idx]
    
    if q["type"] == "mcq":
        is_correct = (answer == correct)
        score = 1.0 if is_correct else 0.0
        percentage = 100.0 if is_correct else 0.0
        result_text = "✅ صحيح" if is_correct else "❌ خطأ"
    else:
        is_correct = (answer == correct)
        score = 1.0 if is_correct else 0.0
        percentage = 100.0 if is_correct else 0.0
        result_text = "✅ صحيح" if is_correct else "❌ خطأ"
    
    data["user_ans"].append(answer)
    data["scores"].append({"score": score, "percentage": percentage})
    data["index"] += 1
    
    bot.answer_callback_query(call.id)
    bot.delete_message(user_id, call.message.message_id)
    
    bot.send_message(user_id, f"📊 تصحيح السؤال {idx+1}: {result_text}\nالنتيجة: {score}/{1} ({percentage:.0f}%)")
    
    send_question(user_id)

def process_essay(message, user_id):
    answer = message.text.strip()
    data = user_answers.get(user_id)
    if not data:
        return
    
    idx = data["index"]
    q = data["questions"][idx]
    correct = data["answers"][idx]
    
    essay_score, essay_percentage = calculate_essay_score(answer, correct)
    
    data["user_ans"].append(answer)
    data["scores"].append({"score": essay_score, "percentage": essay_percentage})
    data["index"] += 1
    
    bot.send_message(user_id, f"📊 تصحيح السؤال {idx+1}:\nالنتيجة: {essay_score:.1f}/{1} ({essay_percentage:.0f}%)\nالإجابة الصحيحة: {correct}")
    
    send_question(user_id)

def finish_exam(user_id):
    data = user_answers.pop(user_id, None)
    if not data:
        return
    
    total = len(data["questions"])
    total_score = sum(s["score"] for s in data["scores"])
    percentage = (total_score / total) * 100
    
    details = []
    for i, (q, user_ans, correct, score_info) in enumerate(zip(data["questions"], data["user_ans"], data["answers"], data["scores"])):
        details.append({
            "type": q["type"],
            "question": q["text"],
            "user_answer": user_ans[:100],
            "correct_answer": correct,
            "score": score_info["score"],
            "max_score": 1.0,
            "percentage": score_info["percentage"]
        })
    
    save_result(data["exam_id"], user_id, total_score, total, percentage, details)
    
    grade_msg, advice, _ = get_grade_message(percentage)
    bot.send_message(user_id, f"🎉 انتهى الاختبار!\nالنتيجة النهائية: {total_score:.1f}/{total} ({percentage:.1f}%)\n\n{grade_msg}\n{advice}")
    
    try:
        pdf_path = generate_certificate(user_id, data["title"], total_score, total, percentage)
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                bot.send_document(user_id, f, caption="📜 شهادتك - @ZeQuiz_Bot", visible_file_name="certificate.pdf")
            os.unlink(pdf_path)
            
            share_markup = InlineKeyboardMarkup()
            share_markup.add(InlineKeyboardButton("📢 شارك نتيجتك", callback_data=f"share_result_{user_id}_{int(percentage)}"))
            bot.send_message(user_id, "🎉 هل تريد مشاركة نتيجتك مع أصدقائك؟", reply_markup=share_markup)
    except Exception as e:
        bot.send_message(user_id, f"❌ حدث خطأ أثناء إنشاء الشهادة: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("share_result_"))
def share_result(call):
    parts = call.data.split("_")
    user_id = int(parts[2])
    percentage = parts[3]
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"🎉 حصلت على نتيجة {percentage}% في اختبار @ZeQuiz_Bot!\n\nشاركها مع أصدقائك: https://t.me/{bot.get_me().username}")

# ========== 4. إنشاء اختبار (يستهلك نقطة واحدة) ==========
temp_exam = {}

@bot.callback_query_handler(func=lambda call: call.data == "create_exam")
def create_exam_start(call):
    user_id = call.message.chat.id
    user = get_user(user_id)
    if user["points"] < 1:
        bot.answer_callback_query(call.id, f"ليس لديك نقاط كافية لإنشاء اختبار. رصيدك: {user['points']:.2f} نقطة. شارك الرابط لتحصل على نقاط!", show_alert=True)
        return
    
    temp_exam[user_id] = {"step": "title", "questions": [], "answers": []}
    bot.send_message(user_id, "📌 أرسل عنوان الاختبار:")
    bot.register_next_step_handler(call.message, process_title)

def process_title(message):
    user_id = message.chat.id
    temp_exam[user_id]["title"] = message.text.strip()
    temp_exam[user_id]["step"] = "question"
    bot.send_message(user_id, "➕ أضف السؤال الأول.\nأرسل السؤال ثم النوع في سطر جديد (mcq/truefalse/text):\nمثال:\nما عاصمة فرنسا؟\ntext")

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "question")
def process_question(message):
    user_id = message.chat.id
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        bot.send_message(user_id, "❌ اكتب السؤال ثم النوع في سطر جديد.")
        return
    q_text = lines[0]
    q_type = lines[1].lower()
    if q_type not in ["text", "mcq", "truefalse"]:
        bot.send_message(user_id, "❌ النوع غير صالح. اختر: text, mcq, truefalse")
        return
    temp_exam[user_id]["current_q"] = {"text": q_text, "type": q_type}
    if q_type == "mcq":
        temp_exam[user_id]["step"] = "mcq_options"
        bot.send_message(user_id, "📋 أرسل الخيارات مفصولة بفواصل (مثال: باريس, لندن, برلين, مدريد):")
    elif q_type == "truefalse":
        temp_exam[user_id]["step"] = "truefalse_answer"
        bot.send_message(user_id, "✅ أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_exam[user_id]["step"] = "essay_answer"
        bot.send_message(user_id, "✍️ أرسل الإجابة النموذجية:")

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "mcq_options")
def process_mcq_options(message):
    user_id = message.chat.id
    opts = [opt.strip() for opt in message.text.split(',')]
    temp_exam[user_id]["current_q"]["options"] = opts
    temp_exam[user_id]["step"] = "mcq_answer"
    bot.send_message(user_id, f"الخيارات: {', '.join(opts)}\nأرسل الإجابة الصحيحة (نص الخيار بالضبط):")

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "mcq_answer")
def process_mcq_answer(message):
    user_id = message.chat.id
    temp_exam[user_id]["current_q"]["answer"] = message.text.strip()
    save_question(user_id)
    ask_next(user_id)

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "truefalse_answer")
def process_truefalse_answer(message):
    user_id = message.chat.id
    ans = message.text.strip()
    if ans not in ["صح", "خطأ"]:
        bot.send_message(user_id, "❌ أرسل 'صح' أو 'خطأ'")
        return
    temp_exam[user_id]["current_q"]["answer"] = ans
    save_question(user_id)
    ask_next(user_id)

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "essay_answer")
def process_essay_answer(message):
    user_id = message.chat.id
    temp_exam[user_id]["current_q"]["answer"] = message.text.strip()
    save_question(user_id)
    ask_next(user_id)

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
    user_id = call.message.chat.id
    if user_id not in temp_exam:
        return
    temp_exam[user_id]["step"] = "question"
    bot.edit_message_text("➕ أضف السؤال التالي (سؤال ثم نوع في سطر جديد):", user_id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_question)

@bot.callback_query_handler(func=lambda call: call.data == "finish_exam")
def finish_creation(call):
    user_id = call.message.chat.id
    if user_id not in temp_exam:
        return
    
    user = get_user(user_id)
    if user["points"] < 1:
        bot.edit_message_text(f"❌ ليس لديك نقاط كافية لإنشاء الاختبار. رصيدك: {user['points']:.2f} نقطة.", user_id, call.message.message_id)
        temp_exam.pop(user_id, None)
        return
    
    update_points(user_id, -1)
    data = temp_exam.pop(user_id)
    eid, code = add_exam(data["title"], data["questions"], data["answers"], user_id)
    new_user = get_user(user_id)
    
    bot.edit_message_text(f"✅ تم إنشاء الاختبار '{data['title']}' بنجاح!\n\n🔗 رابط الاختبار:\nhttps://t.me/{bot.get_me().username}?start=exam_{code}\n\nرمز الاختبار: {code}\nعدد الأسئلة: {len(data['questions'])}\n\n⭐ النقاط المتبقية: {new_user['points']:.2f}", user_id, call.message.message_id)

# ========== 5. لوحة تحكم المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط لمستخدم", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("➖ خصم نقاط من مستخدم", callback_data="admin_remove_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("📋 قائمة جميع الاختبارات", callback_data="admin_all_exams"))
    markup.add(InlineKeyboardButton("📈 نتائج اختبار", callback_data="admin_results"))
    bot.send_message(OWNER_ID, "🔧 لوحة تحكم المالك", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_all_exams")
def admin_all_exams(call):
    if call.message.chat.id != OWNER_ID:
        return
    exams = get_all_exams_by_teacher(OWNER_ID)
    if not exams:
        bot.send_message(OWNER_ID, "لا توجد اختبارات حتى الآن.")
        return
    txt = "📋 قائمة جميع الاختبارات التي أنشأتها:\n\n"
    for eid, title, code, created_at in exams:
        c.execute("SELECT COUNT(*) FROM results WHERE exam_id=?", (eid,))
        participants = c.fetchone()[0]
        txt += f"• {title}\n   رمز: {code}\n   تاريخ: {created_at[:19]}\n   عدد المشاركين: {participants}\n   رابط: https://t.me/{bot.get_me().username}?start=exam_{code}\n\n"
    bot.send_message(OWNER_ID, txt)

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
        pts = float(parts[1])
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
        pts = float(parts[1])
        update_points(uid, -pts)
        bot.send_message(OWNER_ID, f"✅ تم خصم {pts} نقطة من المستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.message.chat.id != OWNER_ID:
        return
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM exams")
    exams = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM results")
    results = c.fetchone()[0]
    c.execute("SELECT SUM(points) FROM users")
    total_points = c.fetchone()[0] or 0
    bot.send_message(OWNER_ID, f"📊 إحصائيات البوت\n👥 المستخدمون: {users}\n📚 الاختبارات: {exams}\n📝 المحاولات: {results}\n⭐ مجموع النقاط: {total_points:.2f}")

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
    txt = f"📈 نتائج اختبار {exam['title']}\n\n"
    for sid, score, total, pct in results:
        txt += f"👤 مستخدم {sid}: {score:.1f}/{total} ({pct:.1f}%)\n"
    bot.send_message(OWNER_ID, txt)

# معالجة الروابط المباشرة
@bot.message_handler(func=lambda m: m.text and m.text.startswith("https://t.me/") and "start=exam_" in m.text)
def handle_exam_link(message):
    code = message.text.split("start=exam_")[1].split()[0]
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(message.chat.id, "❌ رابط غير صحيح.")
        return
    start_exam(message.chat.id, exam)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
