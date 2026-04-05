import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
import requests
import sqlite3
from datetime import datetime
from xhtml2pdf import pisa
from bs4 import BeautifulSoup

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

# ========== إنشاء PDF احترافي ==========
def create_html_for_pdf(original, translated, page_num):
    """إنشاء HTML للتنسيق الجميل للـ PDF"""
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
                @frame footer {{
                    -pdf-frame-content: footerContent;
                    bottom: 0cm;
                    margin-left: 2cm;
                    margin-right: 2cm;
                    height: 1cm;
                }}
            }}
            body {{
                font-family: "DejaVu Sans", "Arial", sans-serif;
                line-height: 1.6;
                direction: ltr;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }}
            .section {{
                margin-bottom: 30px;
                page-break-inside: avoid;
            }}
            .section-title {{
                background-color: #3498db;
                color: white;
                padding: 8px 15px;
                border-radius: 5px;
                margin-bottom: 15px;
                font-size: 16px;
                font-weight: bold;
            }}
            .original-text {{
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                border-left: 4px solid #3498db;
                margin-bottom: 20px;
            }}
            .translated-text {{
                background-color: #f0fdf4;
                padding: 15px;
                border-radius: 8px;
                border-left: 4px solid #22c55e;
                margin-bottom: 20px;
            }}
            .content {{
                font-size: 12px;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
            .separator {{
                height: 1px;
                background-color: #e5e7eb;
                margin: 20px 0;
            }}
            .footer {{
                text-align: center;
                font-size: 9px;
                color: #6c757d;
                margin-top: 30px;
                padding-top: 10px;
                border-top: 1px solid #dee2e6;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>📄 ترجمة المستند</h2>
            <p>Document Translation</p>
        </div>
        
        <div class="section">
            <div class="section-title">📖 النص الأصلي / Original Text</div>
            <div class="original-text">
                <div class="content">{original.replace(chr(10), '<br>')}</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">🌍 النص المترجم / Translated Text</div>
            <div class="translated-text">
                <div class="content">{translated.replace(chr(10), '<br>')}</div>
            </div>
        </div>
        
        <div id="footerContent" class="footer">
            الصفحة {page_num} | تمت الترجمة بواسطة @zakros_onlinebot
        </div>
    </body>
    </html>
    '''

def create_pdf(original, translated, output_path):
    """إنشاء PDF باستخدام xhtml2pdf"""
    # تقسيم النص إلى أجزاء إذا كان طويلاً جداً
    def split_text(text, limit=5000):
        if len(text) <= limit:
            return [text]
        parts = []
        sentences = text.split('. ')
        current = ""
        for sent in sentences:
            if len(current) + len(sent) + 2 <= limit:
                current += sent + ". "
            else:
                parts.append(current)
                current = sent + ". "
        if current:
            parts.append(current)
        return parts
    
    original_parts = split_text(original)
    translated_parts = split_text(translated)
    max_parts = max(len(original_parts), len(translated_parts))
    
    # توسيع القوائم لتكون متساوية الطول
    while len(original_parts) < max_parts:
        original_parts.append("...")
    while len(translated_parts) < max_parts:
        translated_parts.append("...")
    
    # إنشاء PDF لكل جزء ودمجها
    with open(output_path, 'wb') as pdf_file:
        for i, (orig_part, trans_part) in enumerate(zip(original_parts, translated_parts), 1):
            html = create_html_for_pdf(orig_part, trans_part, i)
            pisa_status = pisa.CreatePDF(html, dest=pdf_file)
            if pisa_status.err:
                raise Exception("PDF generation failed")
    return output_path

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
            translated.append(f"[Error in part {i+1}]")
        time.sleep(0.3)
    return " ".join(translated)

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "Session expired, please resend.")
        return
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.send_message(user_id, "Not enough points. Use /share to get free points.")
        return
    update_points(user_id, -1)
    text = session["text"]
    filename = session.get("filename", "user_text.txt")
    try:
        translated = translate_long_text(text, target_lang, user_id=user_id)
        pdf_path = tempfile.mktemp(suffix='.pdf')
        create_pdf(text, translated, pdf_path)
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ Translation to {target_name} completed.\n@zakros_onlinebot", visible_file_name=f"{filename}_{target_lang}.pdf")
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
        f"• Send a .txt file or text message to translate.\n"
        f"• Your points: {user['points']}\n"
        f"• Each translation costs 1 point.\n"
        f"• Get points: /share (4 shares = 1 point) or via referral:\n"
        f"  https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 Bot credit: @zakros_onlinebot"
    )

@bot.message_handler(commands=['share'])
def share_cmd(message):
    user_id = message.chat.id
    add_share(user_id)
    user = get_user(user_id)
    bot.send_message(user_id, f"✅ Thanks for sharing! Your points: {user['points']}")

@bot.message_handler(commands=['admin', 'owner'])
def admin_cmd(message):
    if message.chat.id != OWNER_ID:
        bot.reply_to(message, "Unauthorized.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Points", callback_data="admin_add_points"))
    markup.add(InlineKeyboardButton("📊 Stats", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("👥 Users List", callback_data="admin_users"))
    bot.send_message(OWNER_ID, "🔧 Admin Panel:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.message.chat.id != OWNER_ID:
        bot.answer_callback_query(call.id, "Unauthorized", True)
        return
    if call.data == "admin_add_points":
        msg = bot.send_message(OWNER_ID, "Send user_id and points (e.g., 123456789 5):")
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
        bot.send_message(OWNER_ID, f"📊 Stats:\n👥 Users: {total_users}\n⭐ Points: {total_points}\n📤 Shares: {total_shares}")
    elif call.data == "admin_users":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, points, total_shares FROM users ORDER BY points DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(OWNER_ID, "No users.")
            return
        txt = "🏆 Leaderboard:\n"
        for uid, pts, sh in rows:
            txt += f"👤 {uid} | Points: {pts} | Shares: {sh}\n"
        bot.send_message(OWNER_ID, txt)

def add_points_step(message):
    try:
        parts = message.text.split()
        uid = int(parts[0])
        pts = int(parts[1])
        update_points(uid, pts)
        bot.send_message(OWNER_ID, f"✅ Added {pts} points to user {uid}")
    except:
        bot.send_message(OWNER_ID, "❌ Invalid format. Send: user_id points")

# ========== معالجة الملفات والنصوص ==========
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ Not enough points. Use /share")
        return
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ Send .txt file only.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "❌ Text too short.")
            return
        user_sessions[user_id] = {"text": text, "filename": message.document.file_name}
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(user_id, "✨ Choose language:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    user_id = message.chat.id
    if get_user(user_id)["points"] <= 0:
        bot.reply_to(message, "❌ Not enough points. Use /share")
        return
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "❌ Text too short.")
        return
    user_sessions[user_id] = {"text": text, "filename": "user_text.txt"}
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(user_id, "✨ Choose language:", reply_markup=markup)

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
    bot.send_message(user_id, f"⏳ Starting translation to {target_name}...")
    thread = threading.Thread(target=process_translation, args=(user_id, target, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("✅ Bot is running...")
    bot.remove_webhook()
    bot.infinity_polling()
