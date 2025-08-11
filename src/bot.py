# src/bot.py
from telegram.ext import Application, ApplicationBuilder
from .base import BOT_TOKEN, PUBLIC_URL, PORT, ADMIN_IDS
from .handlers import register
from .db import init_db


def main():
    # دیتابیس را همین ابتدای اجرا بالا می‌آوریم تا نیاز به JobQueue نباشد
    init_db()

    application: Application = ApplicationBuilder().token(BOT_TOKEN).build()
    # لیست ادمین‌ها را در bot_data می‌گذاریم (اگر جای دیگری استفاده می‌شود)
    application.bot_data["admin_ids"] = list(ADMIN_IDS)

    # همهٔ هندلرها
    register(application)

    # اگر آدرس پابلیک (Render) ست شده، با وبهوک اجرا کن؛ وگرنه Polling
    if PUBLIC_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{PUBLIC_URL}/webhook",
            drop_pending_updates=True,
        )
    else:
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
