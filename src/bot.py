# bot.py
from telegram.ext import Updater, CommandHandler
import handlers

import os
TOKEN = os.getenv("BOT_TOKEN")  # توکن ربات از env

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", handlers.start))
    dp.add_handler(CommandHandler("products", handlers.products))
    dp.add_handler(CommandHandler("wallet", handlers.wallet))
    dp.add_handler(CommandHandler("order", handlers.order))
    dp.add_handler(CommandHandler("help", handlers.help_command))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
