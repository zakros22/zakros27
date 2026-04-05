import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import PyPDF2
import docx
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# اللغات المدعومة
LANGUAGES = {
    "ar": "🇸🇦 العربية (فصحى)",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "tr": "🇹🇷 Türkçe",
    "fa": "🇮🇷 فارسی"
}

# تخزين جلسات المستخدمين
user_sessions = {}

# ========== دوال استخراج النص من الملفات ==========
def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    elif ext == '.pdf':
        text = ""
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip()
    elif ext == '.docx':
        doc = docx.Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    else:
        return None

def create_translated_file(original_path, translated_text, output_path):
    """إعادة إنشاء ملف مترجم بنفس نوع الأصلي"""
    ext = os.path.splitext(original_path)[1].lower()
    if ext == '.txt':
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_text)
    elif ext == '.pdf':
        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        y = height - 40
        for line in translated_text.split('\n'):
            if y < 40:
                c.showPage()
                y = height - 40
            for part in [line[i:i+100] for i in range(0, len(line), 100)]:
                c.drawString(40, y, part)
                y -= 15
        c.save()
    elif ext == '.docx':
        doc = docx.Document()
        doc.add_paragraph(translated_text)
        doc.save(output_path)
    else:
        # افتراضي: حفظ كنص عادي
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_text)

# ========== دالة الترجمة (تدعم النصوص الطويلة) ==========
def translate_long_text(text, target_lang, chunk_size=1500):
    translator = GoogleTranslator(source='auto', target=target_lang)
    # تقسيم النص إلى أجزاء
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
            # إعلام المستخدم بالتقدم كل 5 أجزاء
            if (i+1) % 5 == 0 or i+1 == total:
                user_id = user_sessions.get("current_user")
                if user_id:
                    bot.send_message(user_id, f"⏳ جاري الترجمة... {i+1}/{total} جزء")
        except Exception as e:
            translated_parts.append(f"[خطأ في ترجمة جزء {i+1}]")
        time.sleep(0.3)
    return " ".join(translated_parts)

def process_translation(user_id, target_lang, target_name):
    """تعمل في خلفية لترجمة النص وإرسال النتيجة"""
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "❌ انتهت الجلسة، أعد إرسال الملف.")
        return

    original_path = session["original_path"]
    original_text = session["text"]
    original_filename = session["original_name"]

    try:
        translated = translate_long_text(original_text, target_lang)

        # إنشاء ملف مترجم
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{target_lang}{ext}"
        new_path = tempfile.mktemp(suffix=ext)
        create_translated_file(original_path, translated, new_path)

        # إرسال الملف للمستخدم
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
        del user_sessions[user_id]

    except Exception as e:
        bot.send_message(user_id, f"❌ فشلت الترجمة: {str(e)[:200]}")
        if user_id in user_sessions:
            os.unlink(user_sessions[user_id]["original_path"])
            del user_sessions[user_id]

# ========== أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة الملفات الشامل*\n\n"
        "📤 أرسل أي ملف (txt, pdf, docx) وسأقوم بترجمته إلى اللغة التي تختارها.\n"
        "✅ يدعم النصوص الطويلة جدًا (يعمل في الخلفية).\n"
        "👈 أرسل الملف الآن.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    file_name = message.document.file_name
    ext = os.path.splitext(file_name)[1].lower()
    allowed = ['.txt', '.pdf', '.docx']
    if ext not in allowed:
        bot.reply_to(message, f"❌ نوع الملف غير مدعوم. الأنواع المدعومة: {', '.join(allowed)}")
        return

    try:
        # تحميل الملف
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name

        # استخراج النص
        text = extract_text_from_file(tmp_path)
        if not text or len(text.strip()) < 5:
            bot.reply_to(message, "❌ لم يتم العثور على نص صالح في هذا الملف.")
            os.unlink(tmp_path)
            return

        # حفظ الجلسة
        user_sessions[message.chat.id] = {
            "original_path": tmp_path,
            "original_name": file_name,
            "text": text
        }
        user_sessions["current_user"] = message.chat.id

        # عرض أزرار اللغات
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "✨ اختر اللغة التي تريد الترجمة إليها:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ فشل تحميل الملف: {str(e)[:100]}")
        if 'tmp_path' in locals():
            os.unlink(tmp_path)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]

    if user_id not in user_sessions:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"⏳ بدء الترجمة إلى {target_name}... سأرسل الملف فور الانتهاء (قد يستغرق عدة دقائق للنصوص الطويلة).")

    # تشغيل الترجمة في خيط منفصل
    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.start()

if __name__ == "__main__":
    print("✅ بوت الترجمة الشامل يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
