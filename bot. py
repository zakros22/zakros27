import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from groq import Groq
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")
if not GROQ_API_KEY:
    raise Exception("GROQ_API_KEY not set")

client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(BOT_TOKEN)

# تعريف اللهجات
dialects = {
    "iraqi": "اللهجة العراقية",
    "syrian": "اللهجة السورية",
    "fusha": "اللغة العربية الفصحى",
    "egyptian": "اللهجة المصرية",
    "gulf": "اللهجة الخليجية",
    "moroccan": "اللهجة المغربية"
}

def translate_text(text, dialect_name):
    """إرسال النص إلى Groq لترجمته إلى اللهجة المطلوبة"""
    prompt = f"""
أنت مترجم متخصص. قم بتحويل النص التالي إلى {dialect_name} مع الحفاظ على المعنى الأصلي تمامًا.
أخرج النص المترجم فقط، بدون أي مقدمات أو تعليقات أو علامات اقتباس.

النص:
{text}
"""
    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",  # أو mixtral-8x7b-32768
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"فشل الترجمة عبر Groq: {str(e)}")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
        "🌍 أرسل لي ملفًا نصيًا (.txt) وسأقوم بترجمته إلى اللهجة العربية التي تختارها.\n\n"
        "الملف يجب أن يكون بترميز UTF-8. الحد الأقصى للنص: 3000 حرف.")

user_data = {}

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ يرجى إرسال ملف نصي (.txt) فقط.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        original_text = downloaded.decode('utf-8')
        if len(original_text) > 3000:
            bot.reply_to(message, "❌ النص في الملف طويل جدًا (الحد الأقصى 3000 حرف).")
            return
        user_data[message.chat.id] = {"text": original_text, "file_name": message.document.file_name}
        markup = InlineKeyboardMarkup()
        for key, name in dialects.items():
            markup.add(InlineKeyboardButton(name, callback_data=f"dial_{key}"))
        bot.send_message(message.chat.id, "اختر اللهجة التي تريد الترجمة إليها:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ فشل قراءة الملف: {str(e)[:150]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("dial_"))
def handle_dialect(call):
    user_id = call.message.chat.id
    dialect_key = call.data.split("_")[1]
    dialect_name = dialects.get(dialect_key, "لهجة عربية")
    data = user_data.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "انتهت صلاحية الجلسة، أعد إرسال الملف.", show_alert=True)
        return
    original_text = data["text"]
    original_filename = data["file_name"]
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {dialect_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري الترجمة إلى {dialect_name}... قد تستغرق 10-20 ثانية.")
    try:
        translated = translate_text(original_text, dialect_name)
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{dialect_key}{ext}"
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name
        with open(tmp_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {dialect_name}", visible_file_name=new_filename)
        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_data[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ فشل الترجمة: {str(e)[:200]}", user_id, msg.message_id)

if __name__ == "__main__":
    print("✅ بوت الترجمة إلى اللهجات العربية (Groq) يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
