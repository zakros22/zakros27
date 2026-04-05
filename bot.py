import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from googletrans import Translator
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

LANGUAGES = {"ar": "العربية", "en": "English", "fr": "Français"}
user_data = {}

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "أرسل ملف txt لأترجمه إلى PDF")

@bot.message_handler(content_types=['document'])
def handle_doc(m):
    if not m.document.file_name.endswith('.txt'):
        bot.reply_to(m, "أرسل txt فقط")
        return
    file = bot.get_file(m.document.file_id)
    downloaded = bot.download_file(file.file_path)
    text = downloaded.decode('utf-8')
    if len(text) > 2000:
        bot.reply_to(m, "النص طويل (حد 2000)")
        return
    user_data[m.chat.id] = {"text": text, "name": m.document.file_name}
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(m.chat.id, "اختر اللغة:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate(call):
    uid = call.message.chat.id
    target = call.data
    data = user_data.get(uid)
    if not data:
        bot.answer_callback_query(call.id, "انتهت", True)
        return
    bot.answer_callback_query(call.id, "جاري الترجمة...")
    msg = bot.send_message(uid, "⏳ جاري...")
    try:
        translator = Translator()
        translated = translator.translate(data["text"], dest=target).text
        pdf_path = tempfile.mktemp(suffix='.pdf')
        c = canvas.Canvas(pdf_path, pagesize=A4)
        c.drawString(100, 800, "Original:")
        c.drawString(100, 780, data["text"][:200])
        c.drawString(100, 700, "Translated:")
        c.drawString(100, 680, translated[:200])
        c.save()
        with open(pdf_path, 'rb') as f:
            bot.send_document(uid, f, visible_file_name=f"{data['name']}_{target}.pdf")
        os.unlink(pdf_path)
        bot.delete_message(uid, msg.message_id)
        del user_data[uid]
    except Exception as e:
        bot.edit_message_text(f"خطأ: {e}", uid, msg.message_id)

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling()
