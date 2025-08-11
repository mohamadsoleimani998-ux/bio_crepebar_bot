# src/bot.py
import os
import logging

from telegram.ext import Application

# نکته مهم: ایمپورت داخل پکیج src
from src.handlers import register

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("bot")

TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE") or os.getenv("PUBLIC_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or WEBHOOK_BASE
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

PORT = int(os.getenv("PORT", "10000"))  # Render PORT

def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN/BOT_TOKEN not set!")

    application = Application.builder().token(TOKEN).build()

    # همه هندلرها (از جمله /start) اینجا رجیستر می‌شوند
    register(application)

    # اگر آدرس وبهوک داری => وبهوک، وگرنه polling
    if WEBHOOK_URL:
        # PTB v20.6: run_webhook پارامتر on_startup ندارد
        log.info("Starting webhook on port %s ...", PORT)
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:
        log.info("WEBHOOK_URL not set -> falling back to polling")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
