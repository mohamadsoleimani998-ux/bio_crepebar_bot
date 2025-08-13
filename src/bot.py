import logging
import os
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# تنظیمات لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8443"))
PUBLIC_URL = os.environ.get("PUBLIC_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 😊\nربات فروشگاهی شما آماده است!",
        parse_mode=ParseMode.HTML
    )


def main():
    # ساخت اپلیکیشن
    app = ApplicationBuilder().token(TOKEN).build()

    # افزودن دستورات
    app.add_handler(CommandHandler("start", start))

    if PUBLIC_URL:
        # حالت Webhook
        webhook_url = PUBLIC_URL.rstrip("/") + "/"
        log.info("Starting in WEBHOOK mode | url=%s | port=%s", webhook_url, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="",  # در PTB v21 به جای webhook_path باید url_path بگذاریم
            webhook_url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        # حالت Polling
        log.info("Starting in POLLING mode")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
