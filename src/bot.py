import asyncio
import os
from telegram import BotCommand
from telegram.ext import ApplicationBuilder
from .handlers import build_handlers
from .base import BOT_TOKEN, PUBLIC_URL, ADMIN_IDS
from . import db

PORT = int(os.environ.get("PORT", "8000"))

async def on_start(app):
    # DB
    db.init_db()
    # ذخیره ادمین‌ها در bot_data
    app.bot_data["ADMINS"] = ADMIN_IDS or []
    # ست کردن منو/دستورات
    await app.bot.set_my_commands([
        BotCommand("products", "نمایش منو"),
        BotCommand("wallet", "کیف پول"),
        BotCommand("order", "ثبت سفارش"),
        BotCommand("topup", "شارژ کیف پول"),
        BotCommand("contact", "ارتباط با ما"),
        BotCommand("help", "راهنما"),
        BotCommand("game", "بازی"),
        BotCommand("addproduct", "افزودن محصول (ادمین)"),
    ])

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    # handlers
    for h in build_handlers():
        application.add_handler(h)

    application.post_init = on_start

    # Webhook server via PTB (aiohttp)
    public_url = PUBLIC_URL.rstrip("/")
    path = "/webhook"
    webhook_url = f"{public_url}{path}" if public_url else None

    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            secret_token=None,
            webhook_url=webhook_url,
            path=path,
        )
    else:
        # fallback polling (برای اجرای لوکال)
        application.run_polling()

if __name__ == "__main__":
    main()
