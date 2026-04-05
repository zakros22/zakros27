import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
import requests
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont
import sqlite3
from datetime import datetime
import io

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
    conn = sqlite3.connect(DB_NAME)
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

# ========== تحميل خط عالمي ==========
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
FONT_PATH = "DejaVuSans.ttf"
if not os.path.exists(FONT_PATH):
    try:
        print("Downloading font...")
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("Font downloaded.")
    except:
        print("Font download failed.")
        FONT_PATH = None

# تسجيل الخط في reportlab
if FONT_PATH and os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', FONT_PATH))
        FONT_NAME = 'DejaVu'
    except:
        FONT_NAME = 'Helvetica'
else:
    FONT_NAME = 'Helvetica'

def reshape_arabic(text):
    if any('\u0600' <= c <= '\u06FF' for c in text):
        return get_display(arabic_reshaper.reshape(text))
    return text

def text_to_image(text, output_path, width=500):
    """تحويل النص إلى صورة PNG لضمان ظهوره بشكل صحيح"""
    if not FONT_PATH:
        raise Exception("No font")
    font = ImageFont.truetype(FONT_PATH, 14)
    dummy = Image.new('RGB', (1,1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0,0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    img_width = min(width, text_width + 20)
    img_height = text_height + 20
    img = Image.new('RGB', (img_width, img_height), (255,255,255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, font=font, fill=(0,0,0))
    img.save(output_path)
    return output_path

def create_bilingual_pdf(original, translated, output_path):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    y = height - 50
    page_num = 1
    
    def add_page_if_needed(space_needed=100):
        nonlocal y, page_num
        if y - space_needed < 50:
            c.showPage()
            page_num += 1
            y = height - 50
            c.setFont(FONT_NAME, 10)
    
    # تقسيم النصوص إلى فقرات
    def split_paras(text, max_len=400):
        paras = []
        for sent in text.split('. '):
            if not paras:
                paras.append(sent)
            elif len(paras[-1]) + len(sent) + 2 <= max_len:
                paras[-1] += ". " + sent
            else:
                paras.append(sent)
        return [p + "." for p in paras if p]
    
    orig_paras = split_paras(original)
    trans_paras = split_paras(translated)
    max_paras = max(len(orig_paras), len(trans_paras))
    orig_paras += [""] * (max_paras - len(orig_paras))
    trans_paras += [""] * (max_paras - len(trans_paras))
    
    for i, (orig, trans) in enumerate(zip(orig_paras, trans_paras)):
        add_page_if_needed(150)
        # عنوان النص الأصلي
        c.setFillColorRGB(0, 0, 0.6)
        c.setFont(FONT_NAME, 12)
        c.drawString(50, y, f"Original Text - Part {i+1}")
        y -= 20
        # النص الأصلي (كصورة)
        orig_display = reshape_arabic(orig)
        if orig_display.strip():
            img_path = tempfile.mktemp(suffix='.png')
            text_to_image(orig_display, img_path)
            c.drawImage(ImageReader(img_path), 50, y-80, width=500, height=80, preserveAspectRatio=True)
            os.unlink(img_path)
            y -= 90
        # عنوان النص المترجم
        add_page_if_needed(100)
        c.setFillColorRGB(0, 0.5, 0)
        c.drawString(50, y, f"Translated Text - Part {i+1}")
        y -= 20
        # النص المترجم (كصورة)
        trans_display = reshape_arabic(trans)
        if trans_display.strip():
            img_path = tempfile.mktemp(suffix='.png')
            text_to_image(trans_display, img_path)
            c.drawImage(ImageReader(img_path), 50, y-80, width=500, height=80, preserveAspectRatio=True)
            os.unlink(img_path)
            y -= 90
        # فاصل
        y -= 10
        c.setStrokeColorRGB(0.8,0.8,0.8)
        c.line(50, y, 550, y)
        y -= 15
    
    # تذييل
    c.setFillColorRGB(0.5,0.5,0.5)
    c.setFont(FONT_NAME, 8)
    c.drawString(50, 30, f"Page {page_num} - Translation by @zakros_onlinebot")
    c.save()

# ========== الترجمة ==========
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
    translated = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            translated.append(translator.translate(chunk))
            if (i+1) % 5 == 0 or i+1 == total:
                if user_id:
                    bot.send_message(user_id, f"Translation: {i+1}/{total} parts")
        except:
            translated.append(f"[Error part {i+1}]")
        time.sleep(0.3)
    return " ".join(translated)

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "Session expired, resend.")
        return
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.send_message(user_id, "Not enough points. Use /share")
        return
    update_points(user_id, -1)
    text = session["text"]
    filename = session.get("filename", "user_text.txt")
    try:
        translated = translate_long_text(text, target_lang, user_id=user_id)
        pdf_path = tempfile.mktemp(suffix='.pdf')
        create_bilingual_pdf(text, translated, pdf_path)
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ Translated to {target_name}\n@zakros_onlinebot", visible_file_name=f"{filename}_{target_lang}.pdf")
        os.unlink(pdf_path)
        del user_sessions[user_id]
    except Exception as e:
        bot.send_message(user_id, f"❌ Failed: {str(e)[:200]}")
        update_points(user_id, 1)
        if user_id in user_sessions:
            del user_sessions[user_id]

# ========== أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    get_user(user_id)
    if len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.isdigit() and int(ref) != user_id:
            add_referral(int(ref), user_id)
            bot.send_message(user_id, "✅ Referral activated! +1 point for referrer.")
    user = get_user(user_id)
    bot.send_message(user_id,
        f"🌍 Smart Translation Bot\n\n"
        f"Send .txt file or text to translate.\n"
        f"Your points: {user['points']}\n"
        f"Each translation = 1 point.\n"
        f"Get points: /share (4 shares = 1 point) or via referral:\n"
        f"https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"Bot credit: @zakros_onlinebot"
    )

@bot.message_handler(commands=['share'])
def share_cmd(message):
    add_share(message.chat.id)
    user = get_user(message.chat.id)
    bot.send_message(message.chat.id, f"✅ Thanks! Points: {user['points']}")

@bot.message_handler(commands=['admin', 'owner'])
def admin_cmd(message):
    if message.chat.id != OWNER_ID:
        bot.reply_to(message, "Unauthorized")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Points", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("📊 Stats", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("👥 Users", callback_data="admin_users"))
    bot.send_message(OWNER_ID, "🔧 Admin Panel:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "Unauthorized", True)
        return
    if call.data == "admin_add_points":
        msg = bot.send_message(OWNER_ID, "Send: user_id points")
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
        bot.send_message(OWNER_ID, f"Users: {total_users}\nPoints: {total_points}\nShares: {total_shares}")
    elif call.data == "admin_users":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, points, total_shares FROM users ORDER BY points DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(OWNER_ID, "No users")
            return
        txt = "Leaderboard:\n"
        for uid, pts, sh in rows:
            txt += f"{uid} | Points: {pts} | Shares: {sh}\n"
        bot.send_message(OWNER_ID, txt)

def add_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ Added {pts} points to {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ Invalid. Send: user_id points")

# ========== معالجة الملفات والنصوص ==========
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ Not enough points. Use /share")
        return
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ Send .txt file")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "❌ Text too short")
            return
        user_sessions[user_id] = {"text": text, "filename": message.document.file_name}
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(user_id, "Choose language:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ Not enough points. Use /share")
        return
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "❌ Text too short")
        return
    user_sessions[user_id] = {"text": text, "filename": "user_text.txt"}
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(user_id, "Choose language:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target = call.data
    target_name = LANGUAGES[target]
    if user_id not in user_sessions:
        bot.answer_callback_query(call.id, "Session expired, resend.", True)
        return
    bot.answer_callback_query(call.id, f"Translating to {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"Starting translation to {target_name}...")
    thread = threading.Thread(target=process_translation, args=(user_id, target, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("Bot running...")
    bot.remove_webhook()
    bot.infinity_polling()
