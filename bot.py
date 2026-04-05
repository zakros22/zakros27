import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from deep_translator import GoogleTranslator
import sqlite3
from datetime import datetime
import re
import time
import threading
import tempfile
import requests
import zipfile
import io
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. تحميل خط DejaVuSans (يدعم جميع اللغات) ==========
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
FONT_PATH = "DejaVuSans.ttf"

if not os.path.exists(FONT_PATH):
    try:
        print("Downloading font...")
        r = requests.get(FONT_URL, timeout=30)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open("dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf") as f:
                with open(FONT_PATH, "wb") as out:
                    out.write(f.read())
        print("Font installed successfully.")
    except Exception as e:
        print(f"Font download failed: {e}")
        FONT_PATH = None

# ========== 2. إعدادات PDF ==========
class PDF(FPDF):
    def __init__(self):
        super().__init__()
        if FONT_PATH and os.path.exists(FONT_PATH):
            self.add_font('DejaVu', '', FONT_PATH, uni=True)
            self.font_name = 'DejaVu'
        else:
            self.set_font('Helvetica', '', 12)
            self.font_name = 'Helvetica'
        self.add_page()  # فتح صفحة أولى تلقائياً
    
    def header(self):
        if self.page_no() > 1:
            self.set_font(self.font_name, '', 9)
            self.set_text_color(100, 100, 100)
            self.cell(0, 10, f"Page {self.page_no()}", 0, 0, 'C')
            self.ln(8)
    
    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_name, '', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, "Translation by @zakros_onlinebot", 0, 0, 'C')
    
    def add_paragraph(self, title, text, color=(0,0,0)):
        self.set_font(self.font_name, '', 12)
        self.set_text_color(color[0], color[1], color[2])
        self.cell(0, 8, title, ln=1)
        self.set_font(self.font_name, '', 11)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 7, text)
        self.ln(6)

# ========== 3. قاعدة البيانات ==========
DB_NAME = "bot_data.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 2,
        total_shares INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referred_id INTEGER,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    for attempt in range(3):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT points, total_shares FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if not row:
                c.execute("INSERT INTO users (user_id, points, total_shares) VALUES (?,?,?)", (user_id, 2, 0))
                conn.commit()
                conn.close()
                return {"points": 2, "total_shares": 0}
            conn.close()
            return {"points": row[0], "total_shares": row[1]}
        except:
            time.sleep(0.5)
    return {"points": 0, "total_shares": 0}

def update_points(user_id, delta):
    for attempt in range(3):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (delta, user_id))
            conn.commit()
            conn.close()
            return
        except:
            time.sleep(0.5)

def add_share(user_id):
    for attempt in range(3):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE users SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
            c.execute("SELECT total_shares FROM users WHERE user_id=?", (user_id,))
            shares = c.fetchone()[0]
            if shares % 4 == 0:
                c.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()
            return
        except:
            time.sleep(0.5)

def add_referral(referrer_id, referred_id):
    for attempt in range(3):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?,?,?)", (referrer_id, referred_id, datetime.now().isoformat()))
            c.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (referrer_id,))
            conn.commit()
            conn.close()
            return
        except:
            time.sleep(0.5)

# ========== 4. دوال الترجمة والتقدم ==========
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "tr": "Türkçe",
    "fa": "فارسی"
}

user_sessions = {}

def update_progress(user_id, status_msg, stage, percent, details=""):
    bar_length = 20
    filled = int(bar_length * percent // 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    text = f"{stage}\n[{bar}] {percent}%\n{details}"
    bot.edit_message_text(text, user_id, status_msg.message_id)

def split_into_sections(text, max_sentences=3):
    """تقسيم النص إلى أقسام (كل قسم = عدد معين من الجمل)"""
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    sections = []
    current = []
    for sent in sentences:
        current.append(sent)
        if len(current) >= max_sentences:
            sections.append(" ".join(current))
            current = []
    if current:
        sections.append(" ".join(current))
    return sections if sections else [text[:500]]

def translate_section(section, target_lang, user_id, status_msg, idx, total):
    percent = int((idx / total) * 100)
    update_progress(user_id, status_msg, "🌍 جاري الترجمة...", percent, f"الجزء {idx} من {total}")
    translator = GoogleTranslator(source='auto', target=target_lang)
    return translator.translate(section)

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "❌ انتهت الجلسة، أعد إرسال الملف.")
        return
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.send_message(user_id, "❌ رصيدك لا يكفي. استخدم /share")
        return
    original_text = session["text"]
    filename = session.get("filename", "user_text.txt")
    status_msg = bot.send_message(user_id, "🔄 جاري تجهيز المعالجة...")
    try:
        update_progress(user_id, status_msg, "✂️ جاري تقسيم النص إلى أقسام...", 10, "")
        sections = split_into_sections(original_text)
        total_sections = len(sections)
        update_progress(user_id, status_msg, "✅ تم التقسيم", 20, f"عدد الأقسام: {total_sections}")
        
        # ترجمة كل قسم
        translated_sections = []
        for i, sec in enumerate(sections, 1):
            translated = translate_section(sec, target_lang, user_id, status_msg, i, total_sections)
            translated_sections.append(translated)
            time.sleep(0.3)
        
        # إنشاء PDF
        update_progress(user_id, status_msg, "📄 جاري إنشاء PDF...", 85, "تجهيز الصفحات...")
        pdf = PDF()  # الصفحة الأولى مفتوحة تلقائياً
        for i, (orig, trans) in enumerate(zip(sections, translated_sections), 1):
            if i > 1:
                pdf.add_page()
            pdf.add_paragraph(f"📖 Part {i} - Original Text / النص الأصلي", orig, color=(0, 0, 150))
            pdf.add_paragraph(f"🌍 Part {i} - Translated Text / النص المترجم", trans, color=(0, 100, 0))
        
        pdf_path = tempfile.mktemp(suffix='.pdf')
        pdf.output(pdf_path)
        
        # حفظ النقاط وإرسال الملف
        update_points(user_id, -1)
        new_points = get_user(user_id)["points"]
        update_progress(user_id, status_msg, "📤 جاري إرسال الملف...", 100, "اكتمل!")
        time.sleep(1)
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {target_name}\n⭐ النقاط المتبقية: {new_points}\n📌 @zakros_onlinebot", visible_file_name=f"{filename}_{target_lang}.pdf")
        os.unlink(pdf_path)
        bot.delete_message(user_id, status_msg.message_id)
        del user_sessions[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ فشل: {str(e)[:200]}", user_id, status_msg.message_id)

# ========== 5. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    get_user(user_id)
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ تم تفعيل الإحالة! حصل الداعم على نقطة.")
    user = get_user(user_id)
    bot.send_message(user_id,
        f"🌍 بوت الترجمة إلى PDF\n\n"
        f"• أرسل ملف .txt أو نصاً وسأرسل لك PDF مترجماً.\n"
        f"• رصيدك: {user['points']} نقطة\n"
        f"• كل ترجمة = 1 نقطة.\n"
        f"• احصل على نقاط: /share (كل 4 مشاركات = نقطة) أو عبر الإحالة:\n"
        f"  https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 البوت: @zakros_onlinebot"
    )

@bot.message_handler(commands=['share'])
def share_cmd(message):
    user_id = message.chat.id
    add_share(user_id)
    user = get_user(user_id)
    bot.send_message(user_id, f"✅ شكراً للمشاركة! رصيدك: {user['points']} نقطة")

@bot.message_handler(commands=['admin', 'owner'])
def admin_cmd(message):
    if message.chat.id != OWNER_ID:
        bot.reply_to(message, "غير مصرح.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("👥 قائمة المستخدمين", callback_data="admin_users"))
    bot.send_message(OWNER_ID, "🔧 لوحة التحكم:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    if call.data == "admin_add_points":
        msg = bot.send_message(OWNER_ID, "أرسل: معرف_المستخدم عدد_النقاط (مثال: 123456789 5)")
        bot.register_next_step_handler(msg, add_points_step)
    elif call.data == "admin_stats":
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT SUM(points) FROM users")
        total_points = c.fetchone()[0] or 0
        c.execute("SELECT SUM(total_shares) FROM users")
        total_shares = c.fetchone()[0] or 0
        conn.close()
        bot.send_message(OWNER_ID, f"📊 الإحصائيات:\n👥 المستخدمون: {total_users}\n⭐ النقاط: {total_points}\n📤 المشاركات: {total_shares}")
    elif call.data == "admin_users":
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, points, total_shares FROM users ORDER BY points DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(OWNER_ID, "لا يوجد مستخدمون.")
            return
        txt = "🏆 قائمة المستخدمين:\n"
        for uid, pts, sh in rows:
            txt += f"👤 {uid} | نقاط: {pts} | مشاركات: {sh}\n"
        bot.send_message(OWNER_ID, txt)

def add_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ تم إضافة {pts} نقطة للمستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة. أرسل: user_id points")

# ========== 6. معالجة الملفات والنصوص ==========
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. استخدم /share")
        return
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ أرسل ملف .txt فقط")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "❌ النص قصير جداً")
            return
        user_sessions[user_id] = {"text": text, "filename": message.document.file_name}
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(user_id, "✨ اختر اللغة:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. استخدم /share")
        return
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "❌ النص قصير جداً")
        return
    user_sessions[user_id] = {"text": text, "filename": "user_text.txt"}
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(user_id, "✨ اختر اللغة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target = call.data
    target_name = LANGUAGES[target]
    session = user_sessions.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد الإرسال", True)
        return
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    thread = threading.Thread(target=process_translation, args=(user_id, target, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
