import os
import telebot
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not set")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "🎉 *البوت التجريبي يعمل بنجاح!*\n\n"
        "📤 أرسل لي ملفًا نصيًا (.txt) وسأقوم بحفظه وإعادة إرساله إليك كنسخة تجريبية.\n"
        "👈 هذا الاختبار للتأكد من أن البوت يعمل على Heroku بشكل صحيح.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ يرجى إرسال ملف نصي (.txt) فقط.")
        return

    try:
        # تحميل الملف
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode('utf-8')

        # إنشاء ملف جديد باسم مؤقت
        new_filename = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(new_filename, 'w', encoding='utf-8') as f:
            f.write(text)

        # إرسال الملف مرة أخرى للمستخدم
        with open(new_filename, 'rb') as f:
            bot.send_document(
                message.chat.id,
                f,
                caption=f"✅ تم استلام الملف بنجاح! (عدد الأحرف: {len(text)})"
            )
        os.remove(new_filename)

    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {str(e)[:100]}")

@bot.message_handler(func=lambda m: True)
def echo(message):
    bot.reply_to(message, "👈 أرسل ملفًا نصيًا (.txt) أو استخدم /start")

if __name__ == "__main__":
    print("✅ البوت التجريبي يعمل...")
    bot.remove_webhook()
    bot.infinity_polling()
