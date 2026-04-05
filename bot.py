import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from groq import Groq

# ================== الإعدادات ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise Exception("❌ يرجى تعيين BOT_TOKEN و GROQ_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# اللهجات
DIALECTS = {
    "iraqi": "🇮🇶 اللهجة العراقية",
    "syrian": "🇸🇾 اللهجة السورية",
    "fusha": "📖 الفصحى",
    "egyptian": "🇪🇬 اللهجة المصرية",
    "gulf": "🇦🇪 اللهجة الخليجية",
    "moroccan": "🇲🇦 اللهجة المغربية"
}

# تخزين مؤقت
user_texts = {}

def translate(text, dialect):
    prompt = f"حول النص التالي إلى {dialect} مع الحفاظ على المعنى. أخرج النص المترجم فقط:\n\n{text}"
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000
    )
    return completion.choices[0].message.content.strip()

@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id,
        "🌍 أرسل لي ملفًا نصيًا (.txt) وسأترجمه إلى اللهجة التي تختارها.\nالحد الأقصى للنص: 2000 حرف.")

@bot.message_handler(content_types=['document'])
def handle_doc(msg):
    if not msg.document.file_name.endswith('.txt'):
        bot.reply_to(msg, "❌ أرسل ملف .txt فقط.")
        return
    try:
        file_info = bot.get_file(msg.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text) > 2000:
            bot.reply_to(msg, "❌ النص طويل جدًا (2000 حد أقصى).")
            return
        if len(text) < 10:
            bot.reply_to(msg, "❌ النص قصير جدًا.")
            return
        user_texts[msg.chat.id] = {
            "text": text,
            "filename": msg.document.file_name
        }
        markup = InlineKeyboardMarkup()
        for k, v in DIALECTS.items():
            markup.add(InlineKeyboardButton(v, callback_data=k))
        bot.send_message(msg.chat.id, "اختر اللهجة:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(msg, f"❌ خطأ: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in DIALECTS)
def translate_callback(call):
    user_id = call.message.chat.id
    dialect_key = call.data
    dialect_name = DIALECTS[dialect_key]
    data = user_texts.get(user_id)
    if not data:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", True)
        return
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {dialect_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري الترجمة إلى {dialect_name}...")
    try:
        translated = translate(data["text"], dialect_name)
        new_name = f"{os.path.splitext(data['filename'])[0]}_{dialect_key}.txt"
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name
        with open(tmp_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {dialect_name}", visible_file_name=new_name)
        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_texts[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ فشل: {str(e)[:200]}", user_id, msg.message_id)

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
