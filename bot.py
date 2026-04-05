import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# اللغات المدعومة (قم بإضافة أو إزالة ما تشاء)
LANGUAGES = {
    "ar": "🇸🇦 العربية (فصحى)",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "tr": "🇹🇷 Türkçe",
    "fa": "🇮🇷 فارسی"
}

# تسجيل خط يدعم العربية (لـ reportlab)
try:
    # استخدام خط DejaVu الموجود في Heroku (أو يمكنك تحميل خط)
    pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    addMapping('DejaVu', 0, 0, 'DejaVu')
    addMapping('DejaVu', 1, 0, 'DejaVu')
    FONT_NAME = 'DejaVu'
except:
    FONT_NAME = 'Helvetica'  # خط احتياطي

# تخزين جلسات المستخدمين
user_sessions = {}

def translate_long_text(text, target_lang, chunk_size=1500):
    """ترجمة النص الطويل بتقسيمه إلى أجزاء مع إظهار التقدم"""
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
            # إبلاغ المستخدم بالتقدم كل 5 أجزاء
            if (i+1) % 5 == 0 or i+1 == total:
                bot.send_message(user_sessions.get("current_user", 0), f"⏳ الترجمة: {i+1}/{total} جزء")
        except Exception as e:
            translated_parts.append(f"[خطأ في ترجمة الجزء {i+1}]")
        time.sleep(0.5)
    return " ".join(translated_parts)

def create_bilingual_pdf(original_text, translated_text, output_path, bot_credit="@zakros_onlinebot"):
    """
    إنشاء PDF منسق بعمودين أو نصين متسلسلين مع حقوق البوت في الأسفل.
    نظراً لصعوبة الأعمدة في reportlab، سنستخدم نصاً متسلسلاً: النص الأصلي ثم ترجمته.
    """
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=50, rightMargin=50, topMargin=70, bottomMargin=70)
    styles = getSampleStyleSheet()
    
    # تنسيق العناوين والنصوص
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'],
                                 fontName=FONT_NAME, fontSize=18, alignment=TA_CENTER, spaceAfter=20)
    original_style = ParagraphStyle('OriginalStyle', parent=styles['Normal'],
                                    fontName=FONT_NAME, fontSize=12, leading=14, alignment=TA_LEFT,
                                    textColor='darkblue', spaceAfter=10)
    translated_style = ParagraphStyle('TranslatedStyle', parent=styles['Normal'],
                                      fontName=FONT_NAME, fontSize=12, leading=14, alignment=TA_LEFT,
                                      textColor='darkgreen', spaceAfter=20)
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'],
                                  fontName=FONT_NAME, fontSize=9, alignment=TA_CENTER, textColor='gray')
    
    story = []
    # عنوان
    story.append(Paragraph("ترجمة النص", title_style))
    story.append(Spacer(1, 20))
    # النص الأصلي
    story.append(Paragraph("<b>النص الأصلي:</b>", original_style))
    story.append(Paragraph(original_text.replace('\n', '<br/>'), original_style))
    story.append(Spacer(1, 15))
    # النص المترجم
    story.append(Paragraph("<b>النص المترجم:</b>", translated_style))
    story.append(Paragraph(translated_text.replace('\n', '<br/>'), translated_style))
    story.append(Spacer(1, 30))
    # حقوق البوت في التذييل
    story.append(Paragraph(f"<i>تمت الترجمة بواسطة بوت @zakros_onlinebot<br/>حقوق البوت: {bot_credit}</i>", footer_style))
    
    doc.build(story)

def process_translation(user_id, target_lang, target_name):
    """دالة تعمل في خلفية لترجمة النص وإنشاء PDF وإرساله"""
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "❌ انتهت الجلسة، أعد إرسال الملف.")
        return

    original_text = session["text"]
    original_filename = session["filename"]
    original_path = session["path"]

    try:
        # 1. الترجمة
        translated = translate_long_text(original_text, target_lang)
        
        # 2. إنشاء PDF ثنائي اللغة
        base, _ = os.path.splitext(original_filename)
        pdf_filename = f"{base}_{target_lang}_translated.pdf"
        pdf_path = tempfile.mktemp(suffix='.pdf')
        
        create_bilingual_pdf(original_text, translated, pdf_path, bot_credit="@zakros_onlinebot")
        
        # 3. إرسال PDF
        with open(pdf_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {target_name}\n@zakros_onlinebot",
                visible_file_name=pdf_filename
            )
        
        # 4. تنظيف الملفات المؤقتة
        os.unlink(original_path)
        os.unlink(pdf_path)
        del user_sessions[user_id]

    except Exception as e:
        bot.send_message(user_id, f"❌ فشلت الترجمة: {str(e)[:200]}")
        if user_id in user_sessions:
            os.unlink(user_sessions[user_id]["path"])
            del user_sessions[user_id]

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "📄 *بوت ترجمة النصوص إلى PDF منسق*\n\n"
        "أرسل ملفًا نصيًا (.txt) وسأقوم بـ:\n"
        "• ترجمته إلى اللغة التي تختارها\n"
        "• إنشاء PDF يحتوي على النص الأصلي والنص المترجم\n"
        "• إضافة حقوق البوت @zakros_onlinebot في التذييل\n\n"
        "✅ يدعم النصوص الطويلة جدًا (يعمل في الخلفية).\n"
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

        user_sessions[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name,
            "path": tmp_path
        }
        user_sessions["current_user"] = message.chat.id

        # عرض أزرار اللغات
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "✨ اختر اللغة التي تريد الترجمة إليها:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ خطأ في قراءة الملف: {str(e)[:100]}")

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
    bot.send_message(user_id, f"⏳ بدء الترجمة إلى {target_name}... سأرسل ملف PDF فور الانتهاء (قد يستغرق عدة دقائق).")

    # تشغيل الترجمة في خيط منفصل
    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("✅ بوت الترجمة إلى PDF يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
