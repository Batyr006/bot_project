import telebot
import logging
from database import init_db
from handlers import register_handlers

# Токен бота (не забудьте его защитить!) 🔐
BOT_TOKEN = "7566492882:AAGWmTBjRIgUugNOH1wSwcxCh3cc-2sgM2o"

# Инициализация бота с HTML-разметкой сообщений 🎨
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


# Включить подробный лог от TeleBot
logger = telebot.logger
telebot.logger.setLevel(logging.DEBUG)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def main():
    init_db()  # Инициализация базы данных 🚀
    register_handlers(bot)  # Регистрируем все обработчики (handlers) бота 📋
    print("Бот запущен... ✅")
    bot.infinity_polling()  # Бесконечный опрос сервера для получения сообщений 📡

if __name__ == "__main__":
    main()






# BOT_TOKEN = "7566492882:AAGWmTBjRIgUugNOH1wSwcxCh3cc-2sgM2o"
#