import asyncio
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode
from .base import log, BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET
from .handlers import build_handlers
from .db import init_db

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()
    for h in build_handlers():
        app.add_handler(h)
    return app

async def main_async():
    init_db()  # ایمن برای اجرای مکرر
    app = build_app()
    # PTB v21: url_path پارامتر صحیح است (نه webhook_path)
    await app.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path="",
        webhook_url=PUBLIC_URL.rstrip("/"),
        secret_token=WEBHOOK_SECRET,
    )

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
