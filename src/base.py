import os
from telegram.ext import Updater
import handlers

def main():
    # دریافت توکن ربات از محیط
    TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN یا TELEGRAM_TOKEN در متغیرهای محیطی یافت نشد.")

    # ایجاد آپدیتر
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    # ثبت همه هندلرها
    handlers.register_handlers(dp)

    # شروع دریافت پیام‌ها
    port = int(os.environ.get("PORT", 5000))
    if os.getenv("PUBLIC_URL"):
        # وبهوک
        updater.start_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{os.getenv('PUBLIC_URL')}/{TOKEN}"
        )
    else:
        # حالت پولینگ
        updater.start_polling()

    updater.idle()

if __name__ == "__main__":
    main()
