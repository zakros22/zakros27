import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from deep_translator import GoogleTranslator
import tempfile
from fpdf import FPDF

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

# اللغات المدعومة (مجانية، بدون مفاتيح)
LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "tr": "Türkçe"
}

# تخزين النصوص المؤقتة
user_texts = {}

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
        "🌍 *بوت الترجمة المجاني*\n\n"
        "• أرسل لي نصاً أو ملف .txt وسأترجمه.\n"
        "• سأرسل لك PDF يحتوي على النص الأصلي والترجمة.\n"
        "• جميع اللغات مدعومة مجاناً.\n\n"
        "@zakros_onlinebot",
        parse_mode="Markdown")

# ========== معالجة النصوص المباشرة ==========
@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_text(message):
    text = message.text.strip()
    if len(text) < 3:
        bot.reply_to(message, "❌ النص قصير جداً (يحتاج 3 أحرف على الأقل).")
        return
    if len(text) > 4000:
        bot.reply_to(message, "❌ النص طويل جداً (الحد الأقصى 4000 حرف).")
        return
    user_texts[message.chat.id] = text
    markup = InlineKeyboardMarkup()
    for code, name in LANGUAGES.items():
        markup.add(InlineKeyboardButton(name, callback_data=code))
    bot.send_message(message.chat.id, "✨ اختر اللغة:", reply_markup=markup)

# ========== معالجة الملفات النصية ==========
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.chat.id
    file_name = message.document.file_name
    
    if not file_name.lower().endswith('.txt'):
        bot.reply_to(message, "❌ أرسل ملف .txt فقط")
        return
    
    status = bot.reply_to(message, "📥 جاري تحميل الملف...")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # محاولة فك الترميز
        text = None
        for encoding in ['utf-8', 'cp1256', 'windows-1256', 'iso-8859-6', 'latin-1']:
            try:
                text = downloaded.decode(encoding)
                break
            except:
                continue
        
        if text is None:
            bot.edit_message_text("❌ لا يمكن قراءة الملف. تأكد من أنه نصي وبترميز UTF-8.", user_id, status.message_id)
            return
        
        text = text.strip()
        if len(text) < 3:
            bot.edit_message_text("❌ الملف فارغ أو النص قصير جداً.", user_id, status.message_id)
            return
        if len(text) > 4000:
            bot.edit_message_text("❌ الملف كبير جداً (الحد الأقصى 4000 حرف).", user_id, status.message_id)
            return
        
        user_texts[user_id] = text
        bot.delete_message(user_id, status.message_id)
        
        markup = InlineKeyboardMarkup()
        for code, name in LANGUAGES.items():
            markup.add(InlineKeyboardButton(name, callback_data=code))
        bot.send_message(user_id, "✨ اختر اللغة:", reply_markup=markup)
        
    except Exception as e:
        bot.edit_message_text(f"❌ فشل تحميل الملف: {str(e)[:100]}", user_id, status.message_id)

# ========== الترجمة وإنشاء PDF ==========
@bot.callback_query_handler(func=lambda call: call.data in LANGUAGES)
def translate_callback(call):
    user_id = call.message.chat.id
    target_lang = call.data
    target_name = LANGUAGES[target_lang]
    
    text = user_texts.get(user_id)
    if not text:
        bot.answer_callback_query(call.id, "انتهت الجلسة، أعد إرسال النص/الملف", True)
        return
    
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {target_name}...")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    
    status = bot.send_message(user_id, "⏳ جاري الترجمة... (قد تستغرق 5-10 ثوانٍ)")
    
    try:
        # الترجمة باستخدام deep-translator (مجاني)
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = translator.translate(text)
        
        # إنشاء PDF بسيط
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        
        # النص الأصلي
        pdf.set_text_color(0, 0, 150)
        pdf.cell(0, 10, "Original Text / النص الأصلي", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 8, text)
        pdf.ln(8)
        
        # النص المترجم
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 10, "Translated Text / النص المترجم", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 8, translated)
        
        # حقوق البوت
        pdf.set_y(-20)
        pdf.set_font_size(8)
        pdf.set_text_color(128, 128, 128)
        pdf.cell(0, 10, "Translation by @zakros_onlinebot", 0, 0, 'C')
        
        pdf_path = tempfile.mktemp(suffix='.pdf')
        pdf.output(pdf_path)
        
        # إرسال PDF
        with open(pdf_path, 'rb') as f:
            bot.send_document(user_id, f, caption=f"✅ تمت الترجمة إلى {target_name}\n@zakros_onlinebot", visible_file_name=f"translated_{target_lang}.pdf")
        
        os.unlink(pdf_path)
        bot.delete_message(user_id, status.message_id)
        del user_texts[user_id]
        
    except Exception as e:
        bot.edit_message_text(f"❌ فشل الترجمة: {str(e)[:200]}", user_id, status.message_id)

if __name__ == "__main__":
    print("✅ بوت الترجمة المجاني يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
