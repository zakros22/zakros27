import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from groq import Groq

# قراءة المتغيرات البيئية
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise Exception("❌ الرجاء تعيين BOT_TOKEN و GROQ_API_KEY في متغيرات البيئة")

bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# قاموس اللهجات (العربية)
DIALECTS = {
    "iraqi": "🇮🇶 اللهجة العراقية",
    "syrian": "🇸🇾 اللهجة السورية",
    "fusha": "📖 الفصحى",
    "egyptian": "🇪🇬 اللهجة المصرية",
    "gulf": "🇦🇪 اللهجة الخليجية",
    "moroccan": "🇲🇦 اللهجة المغربية"
}

# تخزين مؤقت لبيانات المستخدمين
user_data = {}

def translate_text(text, dialect_name):
    """ترجمة النص إلى اللهجة المطلوبة باستخدام Groq API"""
    prompt = f"""
أنت مترجم خبير. حول النص التالي إلى {dialect_name} مع الحفاظ على المعنى الأصلي والمضمون.
أخرج النص المترجم فقط، بدون أي كلمات إضافية أو علامات تنصيص أو شروح.

النص:
{text}
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"فشل الاتصال بـ Groq: {str(e)}")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة النصوص إلى اللهجات العربية*\n\n"
        "📤 أرسل لي ملفاً نصياً (.txt) وسأقوم بترجمته إلى اللهجة التي تختارها.\n"
        "📏 الحد الأقصى للنص: 2500 حرف.\n"
        "🔤 تأكد أن الملف بترميز UTF-8.\n\n"
        "👈 أرسل الملف الآن.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['document'])
def handle_document(message):
    # التحقق من امتداد الملف
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ يرجى إرسال ملف نصي بامتداد `.txt` فقط.")
        return

    try:
        # تحميل الملف
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')

        # التحقق من الطول
        if len(text) > 2500:
            bot.reply_to(message, "❌ النص في الملف طويل جداً (الحد الأقصى 2500 حرف).")
            return
        if len(text) < 10:
            bot.reply_to(message, "❌ النص قصير جداً (يحتاج على الأقل 10 أحرف).")
            return

        # حفظ البيانات للمستخدم
        user_data[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }

        # إنشاء أزرار اللهجات
        markup = InlineKeyboardMarkup()
        for key, name in DIALECTS.items():
            markup.add(InlineKeyboardButton(name, callback_data=key))

        bot.send_message(message.chat.id, "✨ اختر اللهجة التي تريد الترجمة إليها:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ أثناء قراءة الملف: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: call.data in DIALECTS)
def handle_dialect(call):
    user_id = call.message.chat.id
    dialect_key = call.data
    dialect_name = DIALECTS[dialect_key]

    # استرجاع بيانات المستخدم
    session = user_data.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت صلاحية الجلسة، يرجى إرسال الملف مرة أخرى.", show_alert=True)
        return

    original_text = session["text"]
    original_filename = session["filename"]

    # إعلام المستخدم ببدء الترجمة
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {dialect_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري ترجمة النص إلى {dialect_name}... قد تستغرق 10-20 ثانية.")

    try:
        translated = translate_text(original_text, dialect_name)

        # إنشاء ملف جديد مترجم
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{dialect_key}{ext}"

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name

        with open(tmp_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {dialect_name}",
                visible_file_name=new_filename
            )

        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_data[user_id]  # تنظيف الجلسة

    except Exception as e:
        bot.edit_message_text(f"❌ فشلت الترجمة: {str(e)[:200]}", user_id, msg.message_id)

if __name__ == "__main__":
    print("✅ بوت الترجمة إلى اللهجات العربية يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
