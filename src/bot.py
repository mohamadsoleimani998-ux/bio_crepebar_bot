from __future__ import annotations
import asyncio
from telegram.ext import Application
from .base import SETTINGS
from .handlers import register

# نکته: Start Command در Render =  python -m src.bot
# این فایل، وبهوک PTB را مستقیم بالا می‌آورد (نیازی به uvicorn و ... نیست)

def main():
    application = Application.builder().token(SETTINGS.BOT_TOKEN).build()

    # ثبت هندلرها
    register(application)

    # راه‌اندازی Webhook (بدون آرگومان path چون در PTB20.6 وجود ندارد)
    application.run_webhook(
        listen="0.0.0.0",
        port=SETTINGS.PORT,
        webhook_url=f"{SETTINGS.PUBLIC_URL}/{SETTINGS.BOT_TOKEN}",
        secret_token=None,  # در صورت نیاز می‌توان از Secret Token استفاده کرد
    )

if __name__ == "__main__":
    main()
