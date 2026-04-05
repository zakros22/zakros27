import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import threading
from deep_translator import GoogleTranslator
import time
import re
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# اللغات المدعومة
LANGUAGES = {
    "ar": "🇸🇦 العربية",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "tr": "🇹🇷 Türkçe",
    "fa": "🇮🇷 فارسی"
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
                    bot.send_message(user_id, f"⏳ الترجمة: {i+1}/{total} جزء")
        except Exception as e:
            translated_parts.append(f"[خطأ في الجزء {i+1}]")
        time.sleep(0.3)
    return " ".join(translated_parts)

def create_bilingual_pdf(original_text, translated_text, output_path):
    pdf = FPDF()
    pdf.add_page()
    try:
        pdf.add_font('DejaVu', '', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', uni=True)
        pdf.set_font('DejaVu', '', 12)
    except:
        pdf.set_font('Helvetica', '', 12)

    pdf.set_text_color(0, 0, 150)
    pdf.cell(0, 10, "النص الأصلي:", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 8, original_text)
    pdf.ln(10)

    pdf.set_text_color(0, 100, 0)
    pdf.cell(0, 10, "النص المترجم:", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 8, translated_text)
    pdf.ln(10)

    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 10, "تمت الترجمة بواسطة @zakros_onlinebot", 0, 0, 'C')
    pdf.output(output_path)

def process_translation(user_id, target_lang, target_name):
    session = user_sessions.get(user_id)
    if not session:
        bot.send_message(user_id, "انتهت الجلسة، أعد إرسال النص/الملف.")
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
                caption=f"تمت الترجمة إلى {target_name}\n@zakros_onlinebot",
                visible_file_name=f"{original_filename}_{target_lang}.pdf"
            )
        os.unlink(pdf_path)
        del user_sessions[user_id]
    except Exception as e:
        bot.send_message(user_id, f"فشلت الترجمة: {str(e)[:200]}")
        if user_id in user_sessions:
            del user_sessions[user_id]

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "أرسل لي ملفًا نصيًا (.txt) أو اكتب نصًا مباشرة.\nسأترجمه إلى اللغة التي تختارها وأرسل لك PDF.\nحقوق البوت: @zakros_onlinebot"
    )

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "أرسل ملف .txt فقط.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text.strip()) < 5:
            bot.reply_to(message, "النص قصير جدًا.")
            return
        user_sessions[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "اختر اللغة:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"خطأ: {str(e)[:100]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    text = message.text.strip()
    if len(text) < 5:
        bot.reply_to(message, "النص قصير جدًا.")
        return
    user_sessions[message.chat.id] = {
        "text": text,
        "filename": "user_text.txt"
    }
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(message.chat.id, "اختر اللغة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]

    if user_id not in user_sessions:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال النص/الملف.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"بدء الترجمة إلى {target_name}... سأرسل PDF فور الانتهاء (قد يستغرق عدة دقائق).")

    thread = threading.Thread(target=process_translation, args=(user_id, target_lang, target_name))
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    print("البوت يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
