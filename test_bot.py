import os
import telebot

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "البوت يعمل ✅ أرسل ملف txt")

@bot.message_handler(content_types=['document'])
def handle_doc(m):
    if m.document.file_name.endswith('.txt'):
        bot.reply_to(m, "تم استلام الملف بنجاح ✅")
    else:
        bot.reply_to(m, "أرسل txt فقط")

if __name__ == "__main__":
    bot.infinity_polling()
