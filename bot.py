import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# اللغات المدعومة (يمكنك إضافة المزيد)
LANGUAGES = {
    "ar": "🇸🇦 العربية (فصحى)",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "tr": "🇹🇷 Türkçe"
}

# تخزين مؤقت لبيانات المستخدمين
user_data = {}

def translate_text(text, target_lang, chunk_size=1500):
    """ترجمة النص الطويل بتقسيمه إلى أجزاء"""
    translator = GoogleTranslator(source='auto', target=target_lang)
    # تقسيم النص إلى جمل
    sentences = text.replace('\n', ' ').split('.')
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= chunk_size:
            current += sent + "."
        else:
            if current:
                chunks.append(current)
            current = sent + "."
    if current:
        chunks.append(current)

    translated_parts = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            translated_parts.append(translator.translate(chunk))
            # إرسال تحديث التقدم كل 5 أجزاء
            if (i + 1) % 5 == 0 or i + 1 == total:
                bot.send_message(user_data.get("current_user", 0), f"⏳ الترجمة: {i+1}/{total} جزء")
        except Exception as e:
            translated_parts.append(f"[خطأ في الجزء {i+1}]")
        time.sleep(0.5)
    return " ".join(translated_parts)

def process_translation(user_id, target_lang, target_name):
    """دالة تعمل في الخلفية لترجمة النص وإرسال النتيجة"""
    session = user_data.get(user_id)
    if not session:
        bot.send_message(user_id, "❌ انتهت الجلسة، أعد إرسال الملف.")
        return

    original_text = session["text"]
    original_filename = session["filename"]
    original_path = session["path"]

    try:
        translated = translate_text(original_text, target_lang)

        # إنشاء ملف مترجم جديد
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{target_lang}{ext}"
        new_path = tempfile.mktemp(suffix=ext)

        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(translated)

        # إرسال الملف
        with open(new_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {target_name}",
                visible_file_name=new_filename
            )

        # تنظيف
        os.unlink(original_path)
        os.unlink(new_path)
        del user_data[user_id]

    except Exception as e:
        bot.send_message(user_id, f"❌ فشلت الترجمة: {str(e)[:200]}")
        if user_id in user_data:
            os.unlink(user_data[user_id]["path"])
            del user_data[user_id]

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة الملفات النصية*\n\n"
        "📤 أرسل ملفًا نصيًا (.txt) وسأقوم بترجمته إلى اللغة التي تختارها.\n"
        "✅ يدعم النصوص الطويلة (يعمل في الخلفية).\n"
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

        if len(text.strip()) < 5:
            bot.reply_to(message, "❌ النص قصير جدًا.")
            return

        # حفظ الملف المؤقت
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name

        # حفظ بيانات الجلسة
        user_data[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name,
            "path": tmp_path
        }
        user_data["current_user"] = message.chat.id

        # عرض أزرار اللغات
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "✨ اختر اللغة:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]

    if user_id not in user_data:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"⏳ بدء الترجمة إلى {target_name}... سأرسل الملف فور الانتهاء (قد يستغرق عدة دقائق).")

    # تشغيل الترجمة في خيط منفصل
    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("✅ بوت الترجمة يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
