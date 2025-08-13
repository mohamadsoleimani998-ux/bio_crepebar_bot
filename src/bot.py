import asyncio
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode
from .base import TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT, log
from .handlers import build_handlers
from . import db

def main():
    db.init_db()  # سریع و ایمن

    app = Application.builder().token(TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()

    for h in build_handlers():
        app.add_handler(h)

    if PUBLIC_URL:
        url = PUBLIC_URL.rstrip("/") + f"/{TOKEN}"
        log.info("Webhook at %s", url)
        # NOTE: run_webhook همه چیز را مدیریت می‌کند (init/start/idle/shutdown)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:
        log.warning("PUBLIC_URL not set -> fallback to polling")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
