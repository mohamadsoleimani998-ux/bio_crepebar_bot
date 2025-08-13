import os
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application

from .base import log
from .handlers import build_handlers
from . import db


# ---- ENV ----
BOT_TOKEN       = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
PUBLIC_URL      = (os.environ.get("PUBLIC_URL")
                   or os.environ.get("WEBHOOK_URL")
                   or os.environ.get("WEBHOOK_BASE"))
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT            = int(os.environ.get("PORT", "10000"))


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env is missing.")

    # 1) DB init
    log.info("init_db() running...")
    db.init_db()
    log.info("init_db() done.")

    # 2) Build application with parse_mode
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .parse_mode(ParseMode.HTML)  # ← اینجا اضافه شد
        .build()
    )

    # 3) Handlers
    app.add_handlers(build_handlers())

    # 4) Run
    if PUBLIC_URL:
        webhook_url = PUBLIC_URL.rstrip("/") + "/"
        log.info("Starting in WEBHOOK mode | url=%s | port=%s", webhook_url, PORT)

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_path="/",
            webhook_url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        log.info("Starting in POLLING mode")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
