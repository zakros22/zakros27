import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from deep_translator import GoogleTranslator
import time
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

LANGUAGES = {
    "ar": "🇸🇦 العربية (فصحى)",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français"
}

user_data = {}

def translate_text(text, target_lang):
    """ترجمة النص (بدون تقسيم) - مناسب للنصوص القصيرة والمتوسطة"""
    translator = GoogleTranslator(source='auto', target=target_lang)
    return translator.translate(text)

def create_bilingual_pdf(original, translated, output_path):
    """إنشاء PDF بنصين مع حقوق البوت"""
    pdf = FPDF()
    pdf.add_page()
    # محاولة استخدام خط يدعم العربية (إذا كان موجوداً)
    try:
        pdf.add_font('DejaVu', '', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', uni=True)
        pdf.set_font('DejaVu', '', 12)
    except:
        pdf.set_font('Arial', '', 12)
    
    # النص الأصلي
    pdf.set_text_color(0, 0, 150)
    pdf.cell(0, 10, "النص الأصلي:", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 8, original)
    pdf.ln(10)
    
    # النص المترجم
    pdf.set_text_color(0, 100, 0)
    pdf.cell(0, 10, "النص المترجم:", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 8, translated)
    pdf.ln(10)
    
    # حقوق البوت
    pdf.set_y(-30)
    pdf.set_font_size(8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 10, "تمت الترجمة بواسطة @zakros_onlinebot", 0, 0, 'C')
    
    pdf.output(output_path)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "📄 أرسل ملف txt وسأقوم بترجمته وإرسال PDF\nيدعم النصوص حتى 3000 حرف لضمان السرعة."
    )

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "أرسل ملف txt فقط")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')
        if len(text) > 3000:
            bot.reply_to(message, "النص طويل جداً (الحد 3000 حرف)")
            return
        if len(text) < 10:
            bot.reply_to(message, "النص قصير جداً")
            return
        user_data[message.chat.id] = {"text": text, "filename": message.document.file_name}
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(message.chat.id, "اختر اللغة:", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"خطأ: {e}")

@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target = call.data
    target_name = LANGUAGES[target]
    session = user_data.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت الجلسة", True)
        return
    bot.answer_callback_query(call.id, f"جار الترجمة إلى {target_name}...")
    msg = bot.send_message(user_id, "⏳ جاري الترجمة وإنشاء PDF...")
    try:
        translated = translate_text(session["text"], target)
        pdf_path = tempfile.mktemp(suffix='.pdf')
        create_bilingual_pdf(session["text"], translated, pdf_path)
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {target_name}\n@zakros_onlinebot", visible_file_name=f"{session['filename']}_{target}.pdf")
        os.unlink(pdf_path)
        bot.delete_message(user_id, msg.message_id)
        del user_data[user_id]
    except Exception as e:
        bot.edit_message_text(f"❌ فشل: {str(e)}", user_id, msg.message_id)

if __name__ == "__main__":
    print("بوت الترجمة إلى PDF يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
