import asyncio
from telegram.ext import Application
from .base import BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT
from .handlers import register, startup_warmup

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN/TELEGRAM_TOKEN is not set")

    application = Application.builder().token(BOT_TOKEN).build()

    # ثبت همه‌ی هندلرها
    register(application)

    # آماده‌سازی دیتابیس
    startup_warmup(application)

    # وب‌هوک (بدون پارامترهای نامعتبر)
    # آدرس نهایی: PUBLIC_URL + token (الزام تلگرام برای تمایز)
    url = PUBLIC_URL.rstrip("/")
    webhook_url = f"{url}/{BOT_TOKEN}"
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET,
    )

if __name__ == "__main__":
    main()
