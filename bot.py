import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import PyPDF2
import docx
from deep_translator import GoogleTranslator
import time

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
    """إنشاء ملف مترجم بنفس نوع الأصلي (txt, pdf, docx)"""
    ext = os.path.splitext(original_path)[1].lower()
    if ext == '.txt':
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_text)
    elif ext == '.pdf':
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        y = height - 40
        for line in translated_text.split('\n'):
            if y < 40:
                c.showPage()
                y = height - 40
            # تقسيم السطور الطويلة
            for part in [line[i:i+100] for i in range(0, len(line), 100)]:
                c.drawString(40, y, part)
                y -= 15
        c.save()
    elif ext == '.docx':
        from docx import Document
        doc = Document()
        doc.add_paragraph(translated_text)
        doc.save(output_path)
    else:
        # لأي نوع غير معروف، نحفظ كنص عادي
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_text)

def translate_long_text(text, target_lang, chunk_size=1800):
    """ترجمة النص الطويل بتقسيمه إلى أجزاء (لأن Google Translate API له حد لكل طلب)"""
    translator = GoogleTranslator(source='auto', target=target_lang)
    # تقسيم النص إلى أجزاء حسب الجمل (تقريبي)
    chunks = []
    current_chunk = ""
    for sentence in text.split('.'):
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += sentence + '.'
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence + '.'
    if current_chunk:
        chunks.append(current_chunk)
    
    translated_parts = []
    for i, chunk in enumerate(chunks):
        try:
            translated_parts.append(translator.translate(chunk))
            time.sleep(0.5)  # تجنب الإفراط في الطلبات
        except Exception as e:
            translated_parts.append(f"[خطأ في ترجمة جزء {i+1}]")
    return " ".join(translated_parts)

# ========== أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة الملفات المتقدم*\n\n"
        "📤 أرسل أي ملف (txt, pdf, docx) وسأقوم بترجمته إلى اللغة التي تختارها.\n"
        "⚠️ ملاحظة: الحد العملي للنص حوالي 8000 حرف لضمان السرعة على Heroku.\n"
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

        # لا نحد من طول النص (لكن نحذر إذا كان طويلاً جداً)
        if len(text) > 10000:
            bot.reply_to(message, "⚠️ النص طويل جداً (>10000 حرف). قد تفشل الترجمة بسبب مهلة Heroku. حاول استخدام ملفات أصغر.")
            # نستمر على أي حال

        # حفظ الجلسة
        user_sessions[message.chat.id] = {
            "original_path": tmp_path,
            "original_name": file_name,
            "text": text
        }

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
    session = user_sessions.get(user_id)

    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال الملف.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    msg = bot.send_message(user_id, "⏳ جاري الترجمة... قد تستغرق 30-60 ثانية حسب حجم النص.")

    try:
        original_text = session["text"]
        # ترجمة النص (مع تقسيم إذا لزم)
        translated = translate_long_text(original_text, target_lang)

        # إنشاء ملف مترجم
        original_path = session["original_path"]
        base, ext = os.path.splitext(session["original_name"])
        new_filename = f"{base}_{target_lang}{ext}"
        new_path = tempfile.mktemp(suffix=ext)

        create_translated_file(original_path, translated, new_path)

        # إرسال الملف
        with open(new_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {target_name}",
                visible_file_name=new_filename
            )

        # تنظيف الملفات المؤقتة
        os.unlink(original_path)
        os.unlink(new_path)
        bot.delete_message(user_id, msg.message_id)
        del user_sessions[user_id]

    except Exception as e:
        bot.edit_message_text(f"❌ فشلت الترجمة: {str(e)[:200]}", user_id, msg.message_id)
        if user_id in user_sessions:
            os.unlink(user_sessions[user_id]["original_path"])
            del user_sessions[user_id]

if __name__ == "__main__":
    print("✅ بوت الترجمة المتقدم يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
