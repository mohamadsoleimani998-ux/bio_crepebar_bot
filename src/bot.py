import os
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode

from .base import BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET, log
from . import db
from .handlers import build_handlers

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    # DB
    db.init_db()
    db.ensure_categories()

    # Bot app
    app = Application.builder()\
        .token(BOT_TOKEN)\
        .defaults(Defaults(parse_mode=ParseMode.HTML))\
        .build()

    # handlers
    for h in build_handlers():
        app.add_handler(h)

    # webhook
    # PTB v21: run_webhook(signature=..., secret_token=...)
    # اگر PUBLIC_URL ست شده اجرا با وبهوک
    log.info("Starting with webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        secret_token=WEBHOOK_SECRET,
        webhook_url=PUBLIC_URL,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
