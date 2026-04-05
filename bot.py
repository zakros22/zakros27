import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from deep_translator import GoogleTranslator

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# خيارات الترجمة (لغات مدعومة من Google Translate)
LANGUAGES = {
    "ar": "🇸🇦 العربية (الفصحى)",
    "en": "🇬🇧 الإنجليزية",
    "fr": "🇫🇷 الفرنسية",
    "tr": "🇹🇷 التركية",
    "fa": "🇮🇷 الفارسية"
}

# تخزين مؤقت
user_texts = {}

def translate_text(text, target_lang):
    """ترجمة النص إلى اللغة المستهدفة باستخدام Google Translate (مجاني)"""
    try:
        translator = GoogleTranslator(source='auto', target=target_lang)
        return translator.translate(text)
    except Exception as e:
        raise Exception(f"فشلت الترجمة: {e}")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة النصوص (بدون مفاتيح API)*\n\n"
        "📤 أرسل لي ملفًا نصيًا (.txt) وسأقوم بترجمته إلى اللغة التي تختارها.\n"
        "⚠️ ملاحظة: هذا البوت لا يدعم اللهجات العربية (عراقي، سوري، مصري) لأن الترجمة المجانية لا تدعمها.\n"
        "✅ يمكنك الترجمة إلى العربية الفصحى، الإنجليزية، الفرنسية، وغيرها.\n\n"
        "📏 الحد الأقصى للنص: 2000 حرف.\n"
        "👈 أرسل الملف الآن.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ يرجى إرسال ملف نصي بامتداد `.txt` فقط.")
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')

        if len(text) > 2000:
            bot.reply_to(message, "❌ النص طويل جدًا (الحد الأقصى 2000 حرف).")
            return
        if len(text) < 5:
            bot.reply_to(message, "❌ النص قصير جدًا.")
            return

        user_texts[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }

        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "✨ اختر اللغة التي تريد الترجمة إليها:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def handle_language(call):
    user_id = call.message.chat.id
    target_lang = call.data
    lang_name = LANGUAGES[target_lang]

    session = user_texts.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return

    original_text = session["text"]
    original_filename = session["filename"]

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {lang_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري الترجمة إلى {lang_name}... قد تستغرق 5-10 ثوانٍ.")

    try:
        translated = translate_text(original_text, target_lang)

        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{target_lang}{ext}"

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name

        with open(tmp_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {lang_name}",
                visible_file_name=new_filename
            )

        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_texts[user_id]

    except Exception as e:
        bot.edit_message_text(f"❌ فشلت الترجمة: {str(e)[:200]}", user_id, msg.message_id)
        if user_id in user_texts:
            del user_texts[user_id]

if __name__ == "__main__":
    print("✅ البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
