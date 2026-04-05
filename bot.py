import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# تحميل خط عربي (سيتم تنزيله من الإنترنت)
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf"
FONT_PATH = "NotoSansArabic-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        import requests
        print("Downloading Arabic font...")
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("Font downloaded.")
    except:
        print("Font download failed, using fallback.")
        FONT_PATH = None

def reshape_arabic(text):
    """إعادة تشكيل النص العربي لظهور الحروف متصلة"""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def text_to_image(text, font_path, image_path, width=500):
    """تحويل النص العربي إلى صورة PNG"""
    try:
        font = ImageFont.truetype(font_path, 20)
    except:
        font = ImageFont.load_default()
    # حساب أبعاد الصورة
    dummy_img = Image.new('RGB', (1,1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0,0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    img_width = min(width, text_width + 20)
    img_height = text_height + 20
    img = Image.new('RGB', (img_width, img_height), color=(255,255,255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, font=font, fill=(0,0,0))
    img.save(image_path)
    return image_path

LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Francais",
    "tr": "Turkce"
}

user_sessions = {}

def translate_long_text(text, target_lang, chunk_size=1500, user_id=None):
    translator = GoogleTranslator(source='auto', target=target_lang)
    # تقسيم النص إلى جمل
    sentences = re.split(r'(?<=[.!?؟])\s+', text)
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= chunk_size:
            current += sent + " "
        else:
            if current:
                chunks.append(current.strip())
            current = sent + " "
    if current:
        chunks.append(current.strip())
    translated_parts = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            translated_parts.append(translator.translate(chunk))
            if (i+1) % 5 == 0 or i+1 == total:
                if user_id:
                    bot.send_message(user_id, f"Translation: {i+1}/{total} parts")
        except Exception as e:
            translated_parts.append(f"[Error part {i+1}]")
        time.sleep(0.3)
    return " ".join(translated_parts)

def create_bilingual_pdf(original, translated, output_path):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    y = height - 50
    # تقسيم النصوص إلى فقرات (بحد أقصى 500 حرف لكل فقرة لتتناسب مع الصفحة)
    def split_paragraphs(text, max_len=400):
        paras = []
        current = ""
        for sent in text.split('. '):
            if len(current) + len(sent) + 2 <= max_len:
                current += sent + ". "
            else:
                if current:
                    paras.append(current.strip())
                current = sent + ". "
        if current:
            paras.append(current.strip())
        return paras

    original_paras = split_paragraphs(original)
    translated_paras = split_paragraphs(translated)

    # يجب أن يكون عدد الفقرات متساوياً تقريباً؛ نكرر الترجمة إذا نقصت
    if len(translated_paras) < len(original_paras):
        translated_paras += [""] * (len(original_paras) - len(translated_paras))

    for i, (orig_para, trans_para) in enumerate(zip(original_paras, translated_paras)):
        # النص الأصلي (بعد إعادة التشكيل)
        reshaped_orig = reshape_arabic(orig_para) if any('\u0600' <= c <= '\u06FF' for c in orig_para) else orig_para
        # النص المترجم (إعادة تشكيل إذا كان عربياً)
        reshaped_trans = reshape_arabic(trans_para) if any('\u0600' <= c <= '\u06FF' for c in trans_para) else trans_para

        # إنشاء صورة للنص الأصلي
        img_orig_path = tempfile.mktemp(suffix='.png')
        text_to_image(reshaped_orig, FONT_PATH, img_orig_path, width=500)
        img_orig = ImageReader(img_orig_path)
        c.drawImage(img_orig, 50, y - 100, width=500, height=80, preserveAspectRatio=True)
        y -= 100
        # إنشاء صورة للنص المترجم
        img_trans_path = tempfile.mktemp(suffix='.png')
        text_to_image(reshaped_trans, FONT_PATH, img_trans_path, width=500)
        img_trans = ImageReader(img_trans_path)
        c.drawImage(img_trans, 50, y - 100, width=500, height=80, preserveAspectRatio=True)
        y -= 130
        # إذا كان المكان ضيقاً، نبدأ صفحة جديدة
        if y < 100:
            c.showPage()
            y = height - 50
        # حذف الصور المؤقتة
        os.unlink(img_orig_path)
        os.unlink(img_trans_path)

    # تذييل الحقوق
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5,0.5,0.5)
    c.drawString(50, 30, "Translation by @zakros_onlinebot")
    c.save()

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "Session expired. Please resend the file/text.")
        return

    original_text = session["text"]
    original_filename = session.get("filename", "text_input.txt")

    try:
        translated = translate_long_text(original_text, target_lang, user_id=user_id)
        pdf_path = tempfile.mktemp(suffix='.pdf')
        create_bilingual_pdf(original_text, translated, pdf_path)
        with open(pdf_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"Translation to {target_name} completed. @zakros_onlinebot",
                visible_file_name=f"{original_filename}_{target_lang}.pdf"
            )
        os.unlink(pdf_path)
        del user_sessions[user_id]
    except Exception as e:
        bot.send_message(user_id, f"Translation failed: {str(e)[:200]}")
        if user_id in user_sessions:
            del user_sessions[user_id]

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Send me a .txt file or a text message. I will translate it and send you a PDF.\nBot credit: @zakros_onlinebot"
    )

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "Please send a .txt file only.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "Text is too short.")
            return
        user_sessions[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "Choose target language:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "Text is too short.")
        return
    user_sessions[message.chat.id] = {
        "text": text,
        "filename": "user_text.txt"
    }
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(message.chat.id, "Choose target language:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]

    if user_id not in user_sessions:
        bot.answer_callback_query(call.id, "Session expired. Resend file/text.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"Translating to {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"Starting translation to {target_name}. This may take a few minutes for long texts.")

    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("Bot is running...")
    bot.remove_webhook()
    bot.infinity_polling()
