import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
from groq import Groq

# ========== 1. التحقق من المتغيرات البيئية ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not BOT_TOKEN:
    raise Exception("❌ BOT_TOKEN غير موجود. أضفه في Heroku Config Vars")
if not GROQ_API_KEY:
    raise Exception("❌ GROQ_API_KEY غير موجود. أضفه في Heroku Config Vars")

# ========== 2. تهيئة البوت و Groq ==========
bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# ========== 3. قائمة اللهجات ==========
DIALECTS = {
    "iraqi": "🇮🇶 اللهجة العراقية",
    "syrian": "🇸🇾 اللهجة السورية",
    "fusha": "📖 الفصحى",
    "egyptian": "🇪🇬 اللهجة المصرية",
    "gulf": "🇦🇪 اللهجة الخليجية",
    "moroccan": "🇲🇦 اللهجة المغربية"
}

# تخزين مؤقت لنصوص المستخدمين
user_texts = {}

# ========== 4. دالة الترجمة (مع تقارير الأخطاء) ==========
def translate_text(text, dialect):
    """ترجمة النص إلى اللهجة المطلوبة باستخدام Groq"""
    prompt = f"قم بتحويل النص التالي إلى {dialect} بدقة مع الحفاظ على المعنى. أخرج النص المترجم فقط، بدون أي إضافات:\n\n{text}"
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"Groq API error: {e}")

# ========== 5. أوامر البوت ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    bot.send_message(
        message.chat.id,
        "🌍 *بوت ترجمة النصوص إلى اللهجات العربية*\n\n"
        "📤 أرسل لي ملفًا نصيًا (.txt) وسأقوم بترجمته إلى اللهجة التي تختارها.\n"
        "📏 الحد الأقصى للنص: 2000 حرف.\n"
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
        if len(text) > 2000:
            bot.reply_to(message, "❌ النص طويل جدًا (الحد الأقصى 2000 حرف).")
            return
        if len(text) < 10:
            bot.reply_to(message, "❌ النص قصير جدًا (يحتاج 10 أحرف على الأقل).")
            return

        # حفظ النص واسم الملف للمستخدم
        user_texts[message.chat.id] = {
            "text": text,
            "filename": message.document.file_name
        }

        # عرض أزرار اللهجات
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

    # استرجاع النص المخزن
    session = user_texts.get(user_id)
    if not session:
        bot.answer_callback_query(call.id, "انتهت صلاحية الجلسة، يرجى إرسال الملف مرة أخرى.", show_alert=True)
        return

    original_text = session["text"]
    original_filename = session["filename"]

    # إعلام المستخدم ببدء الترجمة
    bot.answer_callback_query(call.id, f"جاري الترجمة إلى {dialect_name}...")
    msg = bot.send_message(user_id, f"⏳ جاري ترجمة النص إلى {dialect_name}... قد تستغرق 10-20 ثانية.")

    try:
        # الترجمة
        translated = translate_text(original_text, dialect_name)

        # إنشاء ملف جديد مترجم
        base, ext = os.path.splitext(original_filename)
        new_filename = f"{base}_{dialect_key}{ext}"

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
            tmp.write(translated)
            tmp_path = tmp.name

        # إرسال الملف للمستخدم
        with open(tmp_path, 'rb') as f:
            bot.send_document(
                user_id,
                f,
                caption=f"✅ تمت الترجمة إلى {dialect_name}",
                visible_file_name=new_filename
            )

        # تنظيف الملفات المؤقتة والجلسة
        os.unlink(tmp_path)
        bot.delete_message(user_id, msg.message_id)
        del user_texts[user_id]

    except Exception as e:
        error_message = str(e)[:200]
        bot.edit_message_text(f"❌ فشلت الترجمة: {error_message}", user_id, msg.message_id)
        # تنظيف الجلسة
        if user_id in user_texts:
            del user_texts[user_id]

# ========== 6. تشغيل البوت ==========
if __name__ == "__main__":
    print("✅ بوت الترجمة إلى اللهجات العربية يعمل...")
    print(f"Bot token: {BOT_TOKEN[:5]}... (مقنع)")
    print(f"Groq API key: {GROQ_API_KEY[:5]}... (مقنع)")
    bot.remove_webhook()
    bot.infinity_polling()
