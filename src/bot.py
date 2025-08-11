import os
from telegram.ext import Application, ApplicationBuilder
from .base import BOT_TOKEN, PUBLIC_URL, PORT, ADMIN_IDS
from .handlers import register

def main():
    application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    # ذخیره‌ی ادمین‌ها برای استفاده در هندلرها
    application.bot_data["admin_ids"] = list(ADMIN_IDS)

    # ثبت هندلرها
    register(application)

    if PUBLIC_URL:
        # Webhook برای Render
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{PUBLIC_URL}/webhook",
            drop_pending_updates=True,
        )
    else:
        # برای توسعه‌ی محلی
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
