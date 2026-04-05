import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from googletrans import Translator
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)
translator = Translator()

# اللغات المدعومة (العربية الفصحى، الإنجليزية، الفرنسية، التركية)
LANGUAGES = {
    "ar": "🇸🇦 العربية (فصحى)",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "tr": "🇹🇷 Türkçe"
}

user_texts = {}

def translate_with_retry(text, dest, retries=3):
    """إعادة محاولة الترجمة في حالة فشل"""
    for i in range(retries):
        try:
            return translator.translate(text, dest=dest).text
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(2)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة الملفات النصية*\n\n"
        "📤 أرسل ملف `.txt` (حد أقصى 1000 حرف) وسأترجمه.\n"
        "⚠️ الترجمة إلى *العربية الفصحى* فقط (لا توجد لهجات).\n"
        "👈 أرسل الملف الآن.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ أرسل ملف `.txt` فقط.")
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')

        if len(text) > 1000:
            bot.reply_to(message, "❌ النص طويل جداً (الحد الأقصى 1000 حرف).")
            return
        if len(text) < 5:
            bot.reply_to(message, "❌ النص قصير جداً.")
            return

        user_texts[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }

        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "✨ اختر اللغة:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ خطأ في قراءة الملف: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target = call.data
    session = user_texts.get(user_id)

    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {LANGUAGES[target]}...")
    msg = bot.send_message(user_id, f"⏳ جاري الترجمة... قد تستغرق 5-10 ثوانٍ.")

    try:
        translated = translate_with_retry(session["text"], target)

        base, ext = os.path.splitext(session["filename"])
        new_filename = f"{base}_{target}{ext}"

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name

        with open(tmp_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {LANGUAGES[target]}",
                visible_file_name=new_filename
            )

        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_texts[user_id]

    except Exception as e:
        bot.edit_message_text(f"❌ فشل الترجمة: {str(e)[:200]}", user_id, msg.message_id)
        if user_id in user_texts:
            del user_texts[user_id]

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
