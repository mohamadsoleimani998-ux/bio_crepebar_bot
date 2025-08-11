# src/bot.py
import os
from telegram.ext import ApplicationBuilder
from src.handlers import register, startup_warmup  # ایمپورت صحیح داخل پکیج src

BOT_TOKEN = os.environ["BOT_TOKEN"]
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "5000"))

def _post_init(app):
    """هر کاری که باید دقیقاً بعد از استارت انجام شود را اینجا زمان‌بندی کن."""
    # اجرای warmup بلافاصله بعد از استارت
    app.job_queue.run_once(lambda *_: startup_warmup(app), when=0)

def main():
    # post_init برای اجرای کارهای بعد از استارت
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # همه هندلرها
    register(application)

    # اجرای وبهوک — توجه: on_startup/on_shutdown اینجا وجود ندارند
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",                     # نام مسیر داخلی
        webhook_url=f"{PUBLIC_URL}/webhook",   # آدرس پابلیک سرویس در Render
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
