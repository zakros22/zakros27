import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
import requests
import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF
import sqlite3
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. قاعدة البيانات (نقاط، إحالات، مشاركات) ==========
DB_NAME = "bot_data.db"
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 2,
        total_shares INTEGER DEFAULT 0,
        extra_points INTEGER DEFAULT 0
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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT points, total_shares, extra_points FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, points, total_shares, extra_points) VALUES (?,?,?,?)", (user_id, 2, 0, 0))
        conn.commit()
        conn.close()
        return {"points": 2, "total_shares": 0, "extra_points": 0}
    conn.close()
    return {"points": row[0], "total_shares": row[1], "extra_points": row[2]}

def update_points(user_id, delta):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()

def add_share(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET total_shares = total_shares + 1 WHERE user_id=?", (user_id,))
    c.execute("SELECT total_shares FROM users WHERE user_id=?", (user_id,))
    shares = c.fetchone()[0]
    if shares % 4 == 0:
        c.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_referral(referrer_id, referred_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?,?,?)", (referrer_id, referred_id, datetime.now().isoformat()))
    c.execute("UPDATE users SET points = points + 1 WHERE user_id=?", (referrer_id,))
    conn.commit()
    conn.close()

# ========== 2. تحميل خط عالمي (يدعم العربية واللاتينية) ==========
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
FONT_PATH = "DejaVuSans.ttf"
if not os.path.exists(FONT_PATH):
    try:
        print("Downloading DejaVu font...")
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("Font downloaded.")
    except:
        print("Font download failed, using built-in.")
        FONT_PATH = None

def reshape_arabic(text):
    """إعادة تشكيل النص العربي للعرض بشكل صحيح"""
    if any('\u0600' <= c <= '\u06FF' for c in text):
        return get_display(arabic_reshaper.reshape(text))
    return text

class BilingualPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('DejaVu', '', 8)
            self.set_text_color(100,100,100)
            self.cell(0, 10, f"الصفحة {self.page_no()}", 0, 0, 'C')
            self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', '', 8)
        self.set_text_color(150,150,150)
        self.cell(0, 10, "تمت الترجمة بواسطة @zakros_onlinebot", 0, 0, 'C')

def create_bilingual_pdf(original_text, translated_text, output_path):
    pdf = BilingualPDF()
    pdf.add_page()
    if FONT_PATH and os.path.exists(FONT_PATH):
        pdf.add_font('DejaVu', '', FONT_PATH, uni=True)
        pdf.set_font('DejaVu', '', 12)
    else:
        pdf.set_font('Helvetica', '', 12)
    # تقسيم النصوص إلى فقرات قصيرة (كل فقرة لا تتجاوز 500 حرف)
    def split_paragraphs(text, max_len=500):
        paras = []
        for sentence in text.split('. '):
            if not paras:
                paras.append(sentence)
            elif len(paras[-1]) + len(sentence) + 2 <= max_len:
                paras[-1] += ". " + sentence
            else:
                paras.append(sentence)
        return [p + "." for p in paras if p]
    orig_paras = split_paragraphs(original_text)
    trans_paras = split_paragraphs(translated_text)
    # جعل عدد الفقرات متساوياً
    max_paras = max(len(orig_paras), len(trans_paras))
    orig_paras += [""] * (max_paras - len(orig_paras))
    trans_paras += [""] * (max_paras - len(trans_paras))
    for i, (orig, trans) in enumerate(zip(orig_paras, trans_paras)):
        # النص الأصلي (أزرق)
        pdf.set_text_color(0, 0, 150)
        pdf.cell(0, 10, f"النص الأصلي - جزء {i+1}", ln=1)
        pdf.set_text_color(0, 0, 0)
        orig_display = reshape_arabic(orig)
        pdf.multi_cell(0, 8, orig_display)
        pdf.ln(4)
        # النص المترجم (أخضر)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 10, f"النص المترجم - جزء {i+1}", ln=1)
        pdf.set_text_color(0, 0, 0)
        trans_display = reshape_arabic(trans)
        pdf.multi_cell(0, 8, trans_display)
        pdf.ln(8)
        # فاصل بين الفقرات
        pdf.set_draw_color(200,200,200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)
        # صفحة جديدة إذا لزم الأمر
        if pdf.get_y() > 250:
            pdf.add_page()
    pdf.output(output_path)

# ========== 3. الترجمة (بدون حدود) ==========
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "tr": "Türkçe",
    "fa": "فارسی"
}
user_sessions = {}

def translate_long_text(text, target_lang, chunk_size=1500, user_id=None):
    translator = GoogleTranslator(source='auto', target=target_lang)
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= chunk_size:
            current += sent + " "
        else:
            if current:
                chunks.append(current.strip())
            current = sent + " "
    if current:
        chunks.append(current.strip())
    translated_parts = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            translated_parts.append(translator.translate(chunk))
            if (i+1) % 5 == 0 or i+1 == total:
                if user_id:
                    bot.send_message(user_id, f"ترجمة: {i+1}/{total} جزء")
        except Exception as e:
            translated_parts.append(f"[خطأ في الجزء {i+1}]")
        time.sleep(0.3)
    return " ".join(translated_parts)

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "انتهت الجلسة، أعد إرسال النص/الملف.")
        return
    # استهلاك نقطة
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.send_message(user_id, "ليس لديك نقاط كافية. يمكنك الحصول على نقاط عبر مشاركة البوت (/share) أو الإحالات.")
        return
    update_points(user_id, -1)
    original_text = session["text"]
    original_filename = session.get("filename", "user_text.txt")
    try:
        translated = translate_long_text(original_text, target_lang, user_id=user_id)
        pdf_path = tempfile.mktemp(suffix='.pdf')
        create_bilingual_pdf(original_text, translated, pdf_path)
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {target_name}\n@zakros_onlinebot", visible_file_name=f"{original_filename}_{target_lang}.pdf")
        os.unlink(pdf_path)
        del user_sessions[user_id]
    except Exception as e:
        bot.send_message(user_id, f"❌ فشلت الترجمة: {str(e)[:200]}")
        update_points(user_id, 1)  # استرجاع النقطة
        if user_id in user_sessions:
            del user_sessions[user_id]

# ========== 4. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    get_user(user_id)
    # معالجة الإحالة
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ تم تفعيل الإحالة! حصل الداعم على نقطة.")
    user = get_user(user_id)
    bot.send_message(user_id,
        f"🌍 *بوت الترجمة الذكي*\n\n"
        f"• أرسل ملف .txt أو نصاً مباشرة لأترجمه لك.\n"
        f"• رصيدك الحالي: {user['points']} نقطة\n"
        f"• كل ترجمة تستهلك نقطة واحدة.\n"
        f"• يمكنك الحصول على نقاط إضافية عبر:\n"
        f"   - مشاركة البوت: أرسل /share\n"
        f"   - إحالة أصدقاء عبر رابطك:\n"
        f"     https://t.me/{bot.get_me().username}?start={user_id}\n"
        f"📌 حقوق البوت: @zakros_onlinebot",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['share'])
def share_cmd(message):
    user_id = message.chat.id
    add_share(user_id)
    user = get_user(user_id)
    bot.send_message(user_id, f"شكراً لمشاركة البوت! تم إضافة مشاركة. رصيدك الآن: {user['points']} نقطة.")

# ========== 5. لوحة تحكم المالك ==========
@bot.message_handler(commands=['admin', 'owner'])
def admin_cmd(message):
    if message.chat.id != OWNER_ID:
        bot.reply_to(message, "غير مصرح.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("👥 قائمة المستخدمين", callback_data="admin_users"))
    bot.send_message(OWNER_ID, "🔧 لوحة تحكم المالك:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    if call.data == "admin_add_points":
        msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط (مثال: 123456789 5):")
        bot.register_next_step_handler(msg, add_points_step)
    elif call.data == "admin_stats":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT SUM(points) FROM users")
        total_points = c.fetchone()[0] or 0
        c.execute("SELECT SUM(total_shares) FROM users")
        total_shares = c.fetchone()[0] or 0
        conn.close()
        bot.send_message(OWNER_ID, f"📊 إحصائيات:\n👥 مستخدمين: {total_users}\n⭐ نقاط: {total_points}\n📤 مشاركات: {total_shares}")
    elif call.data == "admin_users":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, points, total_shares FROM users ORDER BY points DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(OWNER_ID, "لا يوجد مستخدمون.")
            return
        txt = "🏆 ترتيب المستخدمين:\n"
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
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة. أرسل: `معرف_المستخدم عدد_النقاط`")

# ========== 6. معالجة الملفات والنصوص ==========
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. شارك البوت (/share) لتحصل على نقاط مجانية.")
        return
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ أرسل ملف .txt فقط.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "❌ النص قصير جداً.")
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
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. شارك البوت (/share) لتحصل على نقاط مجانية.")
        return
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "❌ النص قصير جداً.")
        return
    user_sessions[user_id] = {"text": text, "filename": "user_text.txt"}
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(user_id, "✨ اختر اللغة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]
    if user_id not in user_sessions:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال النص/الملف.", show_alert=True)
        return
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"⏳ بدء الترجمة إلى {target_name}... قد تستغرق عدة دقائق.")
    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
