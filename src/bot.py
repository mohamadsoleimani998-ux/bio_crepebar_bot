import os
from telegram.ext import Application
from telegram.constants import ParseMode
from .base import log, BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET
from . import db
from .handlers import build_handlers

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).parse_mode(ParseMode.HTML).build()
    for h in build_handlers():
        app.add_handler(h)

    # webhooks (Render)
    public = (PUBLIC_URL or "").rstrip("/")
    if public:
        path = "/tg-webhook"
        url = f"{public}{path}"
        log.info(f"Setting webhook to: {url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "10000")),
            webhook_url=url,
            secret_token=WEBHOOK_SECRET,
            url_path=path.lstrip("/"),
        )
    else:
        log.info("No PUBLIC_URL -> running polling")
        app.run_polling(allowed_updates=None)

if __name__ == "__main__":
    main()
