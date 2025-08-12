import asyncio
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode
from .base import TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT, log
from .handlers import build_handlers
from . import db

async def main():
    if not TOKEN:
        raise RuntimeError("TOKEN env is missing (TELEGRAM_TOKEN / BOT_TOKEN).")

    db.init_db()

    app = Application.builder().token(TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()

    for h in build_handlers():
        app.add_handler(h)

    # Webhook (Render)
    if PUBLIC_URL:
        # نمونه: https://bio-crepebar-bot.onrender.com/
        url = PUBLIC_URL.rstrip("/") + f"/{TOKEN}"
        log.info("Setting webhook to %s", url)
        await app.bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            secret_token=WEBHOOK_SECRET,
        )
    else:
        # fallback polling (برای توسعه)
        log.warning("PUBLIC_URL not set -> running polling")
        await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
