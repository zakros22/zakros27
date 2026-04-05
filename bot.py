import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from deep_translator import GoogleTranslator
import sqlite3
from datetime import datetime
import re

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
OWNER_ID = 7021542402

# ========== 1. قاعدة البيانات ==========
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

# ========== 2. اللغات ==========
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "tr": "Türkçe",
    "fa": "فارسی"
}

user_sessions = {}

def translate_text(text, target_lang):
    """ترجمة النص مع ضمان الترميز الصحيح"""
    translator = GoogleTranslator(source='auto', target=target_lang)
    try:
        result = translator.translate(text)
        # التأكد من أن النص المرتجع من الترجمة نص عادي
        return str(result).encode('utf-8').decode('utf-8')
    except Exception as e:
        raise Exception(f"Translation error: {e}")

# ========== 3. أوامر البوت ==========
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
        f"🌍 *بوت الترجمة الذكي*\n\n"
        f"• أرسل ملف .txt أو نصاً لأترجمه لك.\n"
        f"• رصيدك: {user['points']} نقطة\n"
        f"• كل ترجمة = 1 نقطة.\n"
        f"• احصل على نقاط: /share (كل 4 مشاركات = نقطة) أو عبر الإحالة:\n"
        f"  https://t.me/{bot.get_me().username}?start={user_id}\n\n"
        f"📌 البوت: @zakros_onlinebot",
        parse_mode="Markdown"
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
        conn = sqlite3.connect(DB_NAME)
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
        conn = sqlite3.connect(DB_NAME)
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

# ========== 4. معالجة الملفات والنصوص ==========
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
        user_sessions[user_id] = text
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
    user_sessions[user_id] = text
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(user_id, "✨ اختر اللغة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target = call.data
    target_name = LANGUAGES[target]
    text = user_sessions.get(user_id)
    if not text:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد الإرسال", True)
        return
    user = get_user(user_id)
    if user["points"] <= 0:
        bot.answer_callback_query(call.id, "لا نقاط كافية", True)
        return
    
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    msg = bot.send_message(user_id, "⏳ جاري الترجمة...")
    
    try:
        translated = translate_text(text, target)
        update_points(user_id, -1)
        new_points = get_user(user_id)["points"]
        
        # إرسال النص الأصلي والمترجم
        response = f"📝 *النص الأصلي:*\n{text}\n\n"
        response += f"🌍 *الترجمة إلى {target_name}:*\n{translated}\n\n"
        response += f"⭐ النقاط المتبقية: {new_points}\n📌 @zakros_onlinebot"
        
        bot.send_message(user_id, response, parse_mode="Markdown")
        bot.delete_message(user_id, msg.message_id)
        del user_sessions[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ فشل الترجمة: {str(e)[:200]}", user_id, msg.message_id)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
