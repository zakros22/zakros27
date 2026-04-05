import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
import requests
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
import sqlite3
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== قاعدة البيانات ==========
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
    conn.close()
    if row:
        return {"points": row[0], "total_shares": row[1], "extra_points": row[2]}
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, points, total_shares, extra_points) VALUES (?,?,?,?)", (user_id, 2, 0, 0))
        conn.commit()
        conn.close()
        return {"points": 2, "total_shares": 0, "extra_points": 0}

def update_points(user_id, points_delta):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (points_delta, user_id))
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

# ========== تحميل خط عربي ==========
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf"
FONT_PATH = "NotoSansArabic-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
    except:
        FONT_PATH = None

def reshape_text(text):
    if any('\u0600' <= c <= '\u06FF' for c in text):
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    return text

def text_to_image(text, output_path, width=500):
    if not FONT_PATH:
        raise Exception("Font not available")
    font = ImageFont.truetype(FONT_PATH, 20)
    dummy = Image.new('RGB', (1,1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0,0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    img_width = min(width, text_width + 20)
    img_height = text_height + 20
    img = Image.new('RGB', (img_width, img_height), color=(255,255,255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, font=font, fill=(0,0,0))
    img.save(output_path)
    return output_path

# ========== الترجمة ==========
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "tr": "Türkçe"
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
    translated = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            translated.append(translator.translate(chunk))
            if (i+1) % 5 == 0 or i+1 == total:
                if user_id:
                    bot.send_message(user_id, f"ترجمة: {i+1}/{total} جزء")
        except:
            translated.append(f"[خطأ في الجزء {i+1}]")
        time.sleep(0.3)
    return " ".join(translated)

def create_bilingual_pdf(original, translated, output_path):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    y = height - 50
    # تقسيم النصوص إلى فقرات قصيرة
    def split_into_paragraphs(text, max_len=400):
        paras = []
        for sentence in text.split('. '):
            if not paras:
                paras.append(sentence)
            elif len(paras[-1]) + len(sentence) + 2 <= max_len:
                paras[-1] += ". " + sentence
            else:
                paras.append(sentence)
        return [p + "." for p in paras if p]
    original_paras = split_into_paragraphs(original)
    translated_paras = split_into_paragraphs(translated)
    max_paras = max(len(original_paras), len(translated_paras))
    # ملء الفقرات الناقصة
    original_paras += [""] * (max_paras - len(original_paras))
    translated_paras += [""] * (max_paras - len(translated_paras))
    for orig, trans in zip(original_paras, translated_paras):
        # النص الأصلي
        orig_display = reshape_text(orig)
        img_orig = tempfile.mktemp(suffix='.png')
        text_to_image(orig_display, img_orig)
        c.drawImage(ImageReader(img_orig), 50, y-80, width=500, height=70, preserveAspectRatio=True)
        y -= 90
        # النص المترجم
        trans_display = reshape_text(trans)
        img_trans = tempfile.mktemp(suffix='.png')
        text_to_image(trans_display, img_trans)
        c.drawImage(ImageReader(img_trans), 50, y-80, width=500, height=70, preserveAspectRatio=True)
        y -= 110
        os.unlink(img_orig)
        os.unlink(img_trans)
        if y < 100:
            c.showPage()
            y = height - 50
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5,0.5,0.5)
    c.drawString(50, 30, "تمت الترجمة بواسطة @zakros_onlinebot")
    c.save()

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "انتهت الجلسة، أعد إرسال النص/الملف.")
        return
    # استهلاك نقطة
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.send_message(user_id, "ليس لديك نقاط كافية. يمكنك الحصول على نقاط إضافية عبر مشاركة البوت (كل 4 مشاركات تمنحك نقطة) أو انتظر إضافة من الأدمن.")
        return
    update_points(user_id, -1)
    original_text = session["text"]
    original_filename = session.get("filename", "text_input.txt")
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

# ========== أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    get_user(user_id)  # إنشاء المستخدم إذا لم يكن موجوداً
    # معالجة الإحالة إذا وجدت
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "تم تفعيل الإحالة! حصل الداعم على نقطة إضافية.")
    bot.send_message(user_id,
        "🌍 *بوت الترجمة الذكي*\n\n"
        "• أرسل ملف .txt أو نصاً مباشرة لأترجمه لك.\n"
        "• كل مستخدم لديه 2 محاولات مجانية.\n"
        "• يمكنك الحصول على نقاط إضافية عبر:\n"
        "   - مشاركة البوت مع أصدقائك (كل 4 مشاركات = نقطة)\n"
        "   - إحالة مستخدم جديد عبر رابطك الخاص\n"
        f"رابط إحالتك: https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        "📌 حقوق البوت: @zakros_onlinebot",
        parse_mode="Markdown"
    )
    # عرض الإحصائيات
    user = get_user(user_id)
    bot.send_message(user_id, f"⭐ رصيدك: {user['points']} نقطة\n📊 مشاركاتك: {user['total_shares']}")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != OWNER_ID:
        bot.reply_to(message, "غير مصرح.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ إضافة نقاط لمستخدم", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("👥 قائمة المستخدمين", callback_data="admin_users"))
    bot.send_message(OWNER_ID, "🔧 لوحة التحكم:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح", True)
        return
    data = call.data
    if data == "admin_add_points":
        msg = bot.send_message(OWNER_ID, "أرسل معرف المستخدم وعدد النقاط مفصولين بمسافة (مثال: 123456789 5):")
        bot.register_next_step_handler(msg, add_points_step)
    elif data == "admin_stats":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT SUM(points) FROM users")
        total_points = c.fetchone()[0] or 0
        c.execute("SELECT SUM(total_shares) FROM users")
        total_shares = c.fetchone()[0] or 0
        conn.close()
        bot.send_message(OWNER_ID, f"📊 إحصائيات البوت:\n👥 عدد المستخدمين: {total_users}\n⭐ مجموع النقاط: {total_points}\n📤 إجمالي المشاركات: {total_shares}")
    elif data == "admin_users":
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
        uid, pts = map(int, message.text.split())
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ تم إضافة {pts} نقطة للمستخدم {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ صيغة غير صحيحة.")

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. شارك البوت لتحصل على نقاط مجانية.")
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

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/') and not m.text.startswith('admin'))
def handle_text(message):
    user_id = message.chat.id
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.reply_to(message, "❌ رصيدك لا يكفي. شارك البوت لتحصل على نقاط مجانية.")
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

# معالجة المشاركة (عند مشاركة المستخدم للبوت، يتم استدعاء الأمر /share)
@bot.message_handler(commands=['share'])
def share_command(message):
    user_id = message.chat.id
    add_share(user_id)
    bot.send_message(user_id, "شكراً لمشاركة البوت! تم إضافة مشاركة. كل 4 مشاركات تمنحك نقطة إضافية.")

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
