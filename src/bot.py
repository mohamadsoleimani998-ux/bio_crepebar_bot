from telegram.ext import Application, AIORateLimiter
from .base import TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT, log
from .handlers import build_handlers
from . import db

def main():
    db.init_db()

    app = Application.builder() \
        .token(TOKEN) \
        .rate_limiter(AIORateLimiter()) \
        .build()

    for h in build_handlers():
        app.add_handler(h)

    # وبهوک ساده: آدرس عمومی کامل در env → PUBLIC_URL
    log.info(f"Starting webhook at {PUBLIC_URL}/")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=PUBLIC_URL,          # مثال: https://bio-crepebar-bot.onrender.com
        secret_token=WEBHOOK_SECRET or None,
    )

if __name__ == "__main__":
    main()
