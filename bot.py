import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
import requests
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# تحميل خط عربي من جوجل (يدعم العربية ولو بشكل بسيط)
FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf"
FONT_PATH = "NotoSansArabic-Regular.ttf"
if not os.path.exists(FONT_PATH):
    try:
        print("Downloading Arabic font...")
        r = requests.get(FONT_URL, timeout=30)
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("Font downloaded.")
    except:
        print("Font download failed, using fallback.")
        FONT_PATH = None

# تسجيل الخط إذا تم تحميله
if FONT_PATH and os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont('NotoSansArabic', FONT_PATH))
        ARABIC_FONT = 'NotoSansArabic'
    except:
        ARABIC_FONT = 'Helvetica'
else:
    ARABIC_FONT = 'Helvetica'

# اللغات المدعومة
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Francais",
    "tr": "Turkce"
}

user_sessions = {}

def translate_long_text(text, target_lang, chunk_size=1500, user_id=None):
    translator = GoogleTranslator(source='auto', target=target_lang)
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
                    bot.send_message(user_id, f"Translation progress: {i+1}/{total} parts")
        except Exception as e:
            translated_parts.append(f"[Error in part {i+1}]")
        time.sleep(0.3)
    return " ".join(translated_parts)

def create_bilingual_pdf(original, translated, output_path):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    c.setFont(ARABIC_FONT, 12)
    
    # النص الأصلي
    c.setFillColorRGB(0, 0, 0.6)
    c.drawString(50, height - 50, "Original Text:")
    c.setFillColorRGB(0, 0, 0)
    y = height - 70
    for line in original.split('\n'):
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont(ARABIC_FONT, 12)
        c.drawString(50, y, line[:100])
        y -= 15
    
    # النص المترجم
    c.showPage()
    c.setFont(ARABIC_FONT, 12)
    c.setFillColorRGB(0, 0.5, 0)
    c.drawString(50, height - 50, "Translated Text:")
    c.setFillColorRGB(0, 0, 0)
    y = height - 70
    for line in translated.split('\n'):
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont(ARABIC_FONT, 12)
        c.drawString(50, y, line[:100])
        y -= 15
    
    # تذييل الحقوق
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.setFont(ARABIC_FONT, 8)
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
        "Send me a .txt file or a text message. I will translate it into the language you choose and send you a PDF.\nBot credit: @zakros_onlinebot"
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
