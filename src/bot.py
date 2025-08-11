from src.handlers import handle_update, startup_warmup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ALL, handle_update))
    app.post_init = startup_warmup

    port = int(os.getenv("PORT", 5000))
    app.run_polling(port=port)

if __name__ == "__main__":
    main()
