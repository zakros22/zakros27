import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from groq import Groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise Exception("BOT_TOKEN and GROQ_API_KEY must be set")

bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# اللهجات المدعومة
DIALECTS = {
    "iraqi": "اللهجة العراقية",
    "syrian": "اللهجة السورية",
    "fusha": "اللغة العربية الفصحى",
    "egyptian": "اللهجة المصرية",
    "gulf": "اللهجة الخليجية",
    "moroccan": "اللهجة المغربية"
}

def translate_text(text, dialect_name):
    """ترجمة النص إلى اللهجة المطلوبة باستخدام Groq"""
    prompt = f"""أنت مترجم محترف. حول النص التالي إلى {dialect_name} بدقة، مع الحفاظ على المعنى الأصلي.
أخرج النص المترجم فقط، بدون أي إضافات أو تعليقات أو علامات اقتباس.

النص:
{text}"""
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"Groq API error: {e}")

# تخزين مؤقت لبيانات المستخدم
user_sessions = {}

@bot.message_handler(commands=['start'])
def start_command(message):
    bot.send_message(message.chat.id,
        "🌍 *بوت ترجمة النصوص إلى اللهجات العربية*\n\n"
        "أرسل لي ملفاً نصياً (.txt) وسأقوم بترجمته إلى اللهجة التي تختارها.\n"
        "الحد الأقصى للنص: 2500 حرف.\n\n"
        "ملاحظة: يجب أن يكون الملف بترميز UTF-8.",
        parse_mode="Markdown")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ يرجى إرسال ملف نصي بامتداد .txt فقط.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text) > 2500:
            bot.reply_to(message, "❌ النص طويل جداً (الحد الأقصى 2500 حرف).")
            return
        # حفظ النص واسم الملف للمستخدم
        user_sessions[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }
        # عرض أزرار اللهجات
        markup = InlineKeyboardMarkup()
        for key, name in DIALECTS.items():
            markup.add(InlineKeyboardButton(name, callback_data=key))
        bot.send_message(message.chat.id, "✨ اختر اللهجة التي تريد الترجمة إليها:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ فشل قراءة الملف: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in DIALECTS)
def handle_dialect(call):
    user_id = call.message.chat.id
    dialect_key = call.data
    dialect_name = DIALECTS[dialect_key]
    session = user_sessions.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return
    original_text = session["text"]
    original_filename = session["filename"]
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {dialect_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري الترجمة إلى {dialect_name}... قد تستغرق 10-20 ثانية.")
    try:
        translated = translate_text(original_text, dialect_name)
        # إنشاء ملف جديد مترجم
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{dialect_key}{ext}"
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name
        with open(tmp_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {dialect_name}", visible_file_name=new_filename)
        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        # تنظيف الجلسة
        del user_sessions[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ خطأ: {str(e)[:200]}", user_id, msg.message_id)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
