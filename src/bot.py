import os
from telegram.ext import ApplicationBuilder
from .base import BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET, tg_defaults, log
from .handlers import build_handlers
from . import db_sqlite as db

PORT = int(os.environ.get("PORT", "10000"))

def main():
    # DB
    db.init_db()

    # BOT
    app = ApplicationBuilder().token(BOT_TOKEN).defaults(tg_defaults).build()

    # Handlers
    for h in build_handlers():
        app.add_handler(h)

    # webhook for PTB 21.x (بدون url_path)
    log.info("Starting webhook on 0.0.0.0:%d -> %s", PORT, PUBLIC_URL)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        secret_token=WEBHOOK_SECRET,
        webhook_url=PUBLIC_URL,   # مثلا https://bio-crepebar-bot.onrender.com/
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
