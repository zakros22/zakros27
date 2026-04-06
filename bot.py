import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import json
import tempfile
import string
import random
from datetime import datetime
import time
import threading
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
    created_at TEXT,
    time_per_question INTEGER DEFAULT 0,
    results_link TEXT UNIQUE
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
    student_name TEXT,
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

def add_exam(title, questions, answers, created_by, time_per_question):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    results_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    c.execute("INSERT INTO exams (title, questions, answers, link_code, created_by, created_at, time_per_question, results_link) VALUES (?,?,?,?,?,?,?,?)",
              (title, json.dumps(questions), json.dumps(answers), code, created_by, datetime.now().isoformat(), time_per_question, results_code))
    conn.commit()
    return c.lastrowid, code, results_code

def get_exam_by_code(code):
    c.execute("SELECT id, title, questions, answers, created_by, time_per_question, results_link FROM exams WHERE link_code=?", (code,))
    row = c.fetchone()
    if row:
        return {"id": row[0], "title": row[1], "questions": json.loads(row[2]), "answers": json.loads(row[3]), "created_by": row[4], "time_per_question": row[5], "results_link": row[6]}
    return None

def get_exam_by_results_link(results_link):
    c.execute("SELECT id, title, created_by FROM exams WHERE results_link=?", (results_link,))
    row = c.fetchone()
    if row:
        return {"id": row[0], "title": row[1], "created_by": row[2]}
    return None

def get_results_by_exam_id(exam_id):
    c.execute("SELECT student_id, student_name, score, total, percentage, date FROM results WHERE exam_id=? ORDER BY percentage DESC", (exam_id,))
    return c.fetchall()

def get_exams_by_user(user_id):
    c.execute("SELECT id, title, link_code, created_at, time_per_question, results_link FROM exams WHERE created_by=? ORDER BY created_at DESC", (user_id,))
    return c.fetchall()

def get_all_exams_by_teacher(teacher_id):
    c.execute("SELECT id, title, link_code, created_at, time_per_question, results_link FROM exams WHERE created_by=? ORDER BY created_at DESC", (teacher_id,))
    return c.fetchall()

def save_result(exam_id, student_id, student_name, score, total, percentage, details):
    c.execute("INSERT INTO results (exam_id, student_id, student_name, score, total, percentage, details, date) VALUES (?,?,?,?,?,?,?,?)",
              (exam_id, student_id, student_name, score, total, percentage, json.dumps(details), datetime.now().isoformat()))
    conn.commit()

def get_user(user_id):
    c.execute("SELECT points, total_shares FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
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
    c.execute("SELECT * FROM referrals WHERE referred_id=?", (referred_id,))
    existing = c.fetchone()
    if existing:
        return False
    c.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?,?,?)", 
              (referrer_id, referred_id, datetime.now().isoformat()))
    update_points(referrer_id, 0.25)
    conn.commit()
    return True

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
    
    pdf.set_text_color(0, 51, 102)
    title_text = reshape_arabic("شهادة إتمام الاختبار")
    pdf.cell(0, 25, title_text, 0, 1, 'C')
    pdf.ln(5)
    
    pdf.set_draw_color(0, 102, 204)
    pdf.line(30, 45, 180, 45)
    
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
    pdf.ln(15)
    
    # حقوق البوت كنص عادي
    pdf.set_font_size(10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "@ZeQuiz_Bot", 0, 1, 'C')
    
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
            success = add_referral(int(ref), user_id)
            if success:
                bot.send_message(user_id, "✅ تم تفعيل الإحالة! حصل الداعم على 0.25 نقطة.")
                bot.send_message(int(ref), "🎉 قام مستخدم جديد بالتسجيل عبر رابطك! تم إضافة 0.25 نقطة إلى رصيدك.")
            else:
                bot.send_message(user_id, "ℹ️ تم تفعيل حسابك مسبقاً، لا يمكن إضافة نقاط إحالة مرة أخرى.")
    
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
    
    for eid, title, code, created_at, time_per_question, results_link in exams:
        time_text = f"{time_per_question} ثانية لكل سؤال" if time_per_question > 0 else "بدون وقت محدد"
        results_url = f"https://t.me/{bot.get_me().username}?start=results_{results_link}"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📊 عرض النتائج", callback_data=f"show_results_{eid}"))
        markup.add(InlineKeyboardButton("📢 مشاركة في قناة", callback_data=f"share_exam_{code}"))
        markup.add(InlineKeyboardButton("🔗 رابط الاختبار", url=f"https://t.me/{bot.get_me().username}?start=exam_{code}"))
        
        bot.send_message(user_id,
            f"📋 *{title}*\n\n"
            f"🆔 رمز الاختبار: `{code}`\n"
            f"⏰ الوقت: {time_text}\n"
            f"📅 التاريخ: {created_at[:19]}\n"
            f"📊 رابط النتائج: [اضغط هنا]({results_url})",
            parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_results_"))
def show_results(call):
    user_id = call.message.chat.id
    exam_id = int(call.data.split("_")[2])
    
    c.execute("SELECT created_by, title FROM exams WHERE id=?", (exam_id,))
    exam = c.fetchone()
    if not exam or exam[0] != user_id:
        bot.answer_callback_query(call.id, "غير مصرح لك بعرض نتائج هذا الاختبار.", True)
        return
    
    results = get_results_by_exam_id(exam_id)
    if not results:
        bot.send_message(user_id, f"📊 لا توجد نتائج لاختبار {exam[1]} بعد.")
        return
    
    txt = f"📊 *نتائج اختبار {exam[1]}*\n\n"
    for student_id, student_name, score, total, percentage, date in results:
        name = student_name if student_name else f"مستخدم {student_id}"
        txt += f"👤 {name}\n   🎯 {score:.1f}/{total} ({percentage:.1f}%)\n   📅 {date[:16]}\n\n"
    
    bot.send_message(user_id, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("share_exam_"))
def share_exam_channel(call):
    user_id = call.message.chat.id
    code = call.data.split("_")[2]
    exam = get_exam_by_code(code)
    if not exam or exam["created_by"] != user_id:
        bot.answer_callback_query(call.id, "غير مصرح.", True)
        return
    
    bot.answer_callback_query(call.id)
    
    direct_link = f"https://t.me/{bot.get_me().username}?start=exam_{code}"
    
    bot.send_message(user_id,
        f"📢 لمشاركة الاختبار في قناة تلغرام:\n\n"
        f"1. أضف البوت @{bot.get_me().username} أدمن في قناتك\n"
        f"2. انسخ الرابط التالي وأرسله في قناتك:\n"
        f"{direct_link}\n\n"
        f"📝 نص جاهز للنشر في القناة:\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎓 اختبار: {exam['title']}\n\n"
        f"📝 اختبر معلوماتك الآن!\n"
        f"{direct_link}\n\n"
        f"@ZeQuiz_Bot\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        disable_web_page_preview=True)

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
    
    # طلب اسم المستخدم
    msg = bot.send_message(user_id, "📝 أرسل اسمك (سيظهر في الشهادة والنتائج):")
    bot.register_next_step_handler(msg, process_student_name, exam)

def process_student_name(message, exam):
    user_id = message.chat.id
    student_name = message.text.strip()
    
    user_answers[user_id] = {
        "exam_id": exam["id"],
        "title": exam["title"],
        "questions": exam["questions"],
        "answers": exam["answers"],
        "user_ans": [],
        "scores": [],
        "index": 0,
        "time_per_question": exam["time_per_question"],
        "timer_active": False,
        "timer_thread": None,
        "current_message_id": None,
        "student_name": student_name
    }
    send_question(user_id)

user_answers = {}

def start_timer(user_id, duration):
    data = user_answers.get(user_id)
    if not data:
        return
    
    data["timer_active"] = True
    start_time = time.time()
    end_time = start_time + duration
    
    while data["timer_active"] and time.time() < end_time:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        
        if data["current_message_id"]:
            try:
                bot.edit_message_text(
                    f"⏰ الوقت المتبقي: {remaining} ثانية", 
                    user_id, 
                    data["current_message_id"]
                )
            except:
                pass
        time.sleep(1)
    
    if data["timer_active"]:
        data["timer_active"] = False
        bot.send_message(user_id, f"⏰ انتهى وقت السؤال {data['index'] + 1}! سيتم الانتقال للسؤال التالي.")
        
        data["user_ans"].append("(لم يجب)")
        data["scores"].append({"score": 0, "percentage": 0})
        data["index"] += 1
        
        if data["current_message_id"]:
            try:
                bot.delete_message(user_id, data["current_message_id"])
            except:
                pass
            data["current_message_id"] = None
        
        send_question(user_id)

def send_question(user_id):
    data = user_answers.get(user_id)
    if not data:
        return
    
    idx = data["index"]
    if idx >= len(data["questions"]):
        finish_exam(user_id)
        return
    
    q = data["questions"][idx]
    
    if data["time_per_question"] > 0:
        timer_msg = bot.send_message(user_id, f"⏰ سيبدأ السؤال خلال 3 ثوان...")
        time.sleep(3)
        bot.delete_message(user_id, timer_msg.message_id)
        
        timer_msg = bot.send_message(user_id, f"⏰ الوقت المتبقي: {data['time_per_question']} ثانية")
        data["current_message_id"] = timer_msg.message_id
        
        timer_thread = threading.Thread(target=start_timer, args=(user_id, data["time_per_question"]))
        timer_thread.daemon = True
        timer_thread.start()
    
    if q["type"] == "mcq":
        markup = InlineKeyboardMarkup(row_width=1)
        buttons = []
        for opt in q["options"]:
            buttons.append(InlineKeyboardButton(opt, callback_data=f"ans_{opt}"))
        markup.add(*buttons)
        bot.send_message(user_id, f"📝 السؤال {idx+1}: {q['text']}", reply_markup=markup)
    elif q["type"] == "truefalse":
        markup = InlineKeyboardMarkup(row_width=2)
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
    
    data["timer_active"] = False
    
    if data["current_message_id"]:
        try:
            bot.delete_message(user_id, data["current_message_id"])
        except:
            pass
        data["current_message_id"] = None
    
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
    
    data["timer_active"] = False
    
    if data["current_message_id"]:
        try:
            bot.delete_message(user_id, data["current_message_id"])
        except:
            pass
        data["current_message_id"] = None
    
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
    
    save_result(data["exam_id"], user_id, data["student_name"], total_score, total, percentage, details)
    
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

# معالجة رابط النتائج
@bot.message_handler(func=lambda m: m.text and m.text.startswith("https://t.me/") and "start=results_" in m.text)
def handle_results_link(message):
    results_code = message.text.split("start=results_")[1].split()[0]
    exam = get_exam_by_results_link(results_code)
    if not exam:
        bot.send_message(message.chat.id, "❌ رابط غير صحيح.")
        return
    
    results = get_results_by_exam_id(exam["id"])
    if not results:
        bot.send_message(message.chat.id, f"📊 لا توجد نتائج لاختبار {exam['title']} بعد.")
        return
    
    txt = f"📊 *نتائج اختبار {exam['title']}*\n\n"
    for student_id, student_name, score, total, percentage, date in results:
        name = student_name if student_name else f"مستخدم {student_id}"
        txt += f"👤 {name}\n   🎯 {score:.1f}/{total} ({percentage:.1f}%)\n   📅 {date[:16]}\n\n"
    
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

# ========== 4. إنشاء اختبار ==========
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
    temp_exam[user_id]["step"] = "time_per_question"
    bot.send_message(user_id, "⏰ أرسل الوقت المخصص لكل سؤال (بالثواني)\nمثال: 30 (أي 30 ثانية لكل سؤال)\nأو أرسل 0 إذا لا يوجد وقت محدد:")

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "time_per_question")
def process_time_per_question(message):
    user_id = message.chat.id
    try:
        time_per_question = int(message.text.strip())
        temp_exam[user_id]["time_per_question"] = time_per_question
        temp_exam[user_id]["step"] = "question"
        bot.send_message(user_id, "➕ أضف السؤال الأول.\nأرسل السؤال ثم النوع في سطر جديد (mcq/truefalse/text):\nمثال:\nما عاصمة فرنسا؟\ntext")
    except:
        bot.send_message(user_id, "❌ أرسل رقماً صحيحاً (بالثواني). مثال: 30")

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
        bot.send_message(user_id, "📋 أرسل خيارات السؤال (كل خيار في سطر منفرد):\nمثال:\nخيار 1\nخيار 2\nخيار 3")
    elif q_type == "truefalse":
        temp_exam[user_id]["step"] = "truefalse_answer"
        bot.send_message(user_id, "✅ أرسل الإجابة الصحيحة (صح أو خطأ):")
    else:
        temp_exam[user_id]["step"] = "essay_answer"
        bot.send_message(user_id, "✍️ أرسل الإجابة النموذجية:")

@bot.message_handler(func=lambda m: m.chat.id in temp_exam and temp_exam.get(m.chat.id, {}).get("step") == "mcq_options")
def process_mcq_options(message):
    user_id = message.chat.id
    opts = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
    if len(opts) < 2:
        bot.send_message(user_id, "❌ يجب إدخال خيارين على الأقل (كل خيار في سطر منفرد).")
        return
    temp_exam[user_id]["current_q"]["options"] = opts
    temp_exam[user_id]["step"] = "mcq_answer"
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(opts)])
    bot.send_message(user_id, f"الخيارات:\n{options_text}\n\nأرسل نص الإجابة الصحيحة (كما هو مكتوب بالضبط):")

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
    time_text = f"{data['time_per_question']} ثانية لكل سؤال" if data["time_per_question"] > 0 else "بدون وقت محدد"
    
    eid, code, results_code = add_exam(data["title"], data["questions"], data["answers"], user_id, data["time_per_question"])
    new_user = get_user(user_id)
    results_url = f"https://t.me/{bot.get_me().username}?start=results_{results_code}"
    
    bot.edit_message_text(
        f"✅ تم إنشاء الاختبار '{data['title']}' بنجاح!\n\n"
        f"⏰ الوقت لكل سؤال: {time_text}\n"
        f"🔗 رابط الاختبار:\nhttps://t.me/{bot.get_me().username}?start=exam_{code}\n\n"
        f"📊 رابط النتائج (مشاركة مع الطلاب):\n{results_url}\n\n"
        f"🆔 رمز الاختبار: `{code}`\n"
        f"📋 عدد الأسئلة: {len(data['questions'])}\n\n"
        f"⭐ النقاط المتبقية: {new_user['points']:.2f}",
        user_id, call.message.message_id, parse_mode="Markdown", disable_web_page_preview=True)

# ========== 5. لوحة تحكم المالك ==========
@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط لمستخدم", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("➖ خصم نقاط من مستخدم", callback_data="admin_remove_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("📋 قائمة جميع الاختبارات", callback_data="admin_all_exams"))
    markup.add(InlineKeyboardButton("📈 نتائج اختبار", callback_data="admin_results"))
    markup.add(InlineKeyboardButton("📢 إذاعة للجميع", callback_data="admin_broadcast"))
    bot.send_message(OWNER_ID, "🔧 لوحة تحكم المالك", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def admin_broadcast(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    msg = bot.send_message(OWNER_ID, "📢 أرسل الرسالة التي تريد إذاعتها لجميع مستخدمي البوت:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    broadcast_text = message.text
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    success = 0
    fail = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 إذاعة من المالك:\n\n{broadcast_text}\n\n@ZeQuiz_Bot")
            success += 1
        except:
            fail += 1
        time.sleep(0.05)
    bot.send_message(OWNER_ID, f"✅ تم إرسال الإذاعة إلى {success} مستخدم.\n❌ فشل الإرسال إلى {fail} مستخدم.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_all_exams")
def admin_all_exams(call):
    if call.message.chat.id != OWNER_ID:
        return
    exams = get_all_exams_by_teacher(OWNER_ID)
    if not exams:
        bot.send_message(OWNER_ID, "لا توجد اختبارات حتى الآن.")
        return
    txt = "📋 قائمة جميع الاختبارات التي أنشأتها:\n\n"
    for eid, title, code, created_at, time_per_question, results_link in exams:
        time_text = f"{time_per_question} ثانية لكل سؤال" if time_per_question > 0 else "بدون وقت"
        c.execute("SELECT COUNT(*) FROM results WHERE exam_id=?", (eid,))
        participants = c.fetchone()[0]
        txt += f"• {title}\n   رمز: {code}\n   الوقت: {time_text}\n   تاريخ: {created_at[:19]}\n   عدد المشاركين: {participants}\n   رابط: https://t.me/{bot.get_me().username}?start=exam_{code}\n\n"
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
    bot.register_next_step_handler(msg, show_results_by_code)

def show_results_by_code(message):
    code = message.text.strip().upper()
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(OWNER_ID, "❌ رمز غير صحيح.")
        return
    results = get_results_by_exam_id(exam["id"])
    if not results:
        bot.send_message(OWNER_ID, f"لا توجد نتائج لاختبار {exam['title']}.")
        return
    txt = f"📈 نتائج اختبار {exam['title']}\n\n"
    for sid, name, score, total, pct, date in results:
        student_name = name if name else f"مستخدم {sid}"
        txt += f"👤 {student_name}\n   🎯 {score:.1f}/{total} ({pct:.1f}%)\n   📅 {date[:16]}\n\n"
    bot.send_message(OWNER_ID, txt)

# معالجة الروابط المباشرة للاختبارات
@bot.message_handler(func=lambda m: m.text and m.text.startswith("https://t.me/") and "start=exam_" in m.text)
def handle_exam_link(message):
    code = message.text.split("start=exam_")[1].split()[0]
    exam = get_exam_by_code(code)
    if not exam:
        bot.send_message(message.chat.id, "❌ رابط غير صحيح.")
        return
    
    msg = bot.send_message(message.chat.id, "📝 أرسل اسمك (سيظهر في الشهادة والنتائج):")
    bot.register_next_step_handler(msg, process_student_name, exam)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
