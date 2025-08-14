# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults, AIORateLimiter

from .base import TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT, log
from .handlers import build_handlers
from . import db


def main():
    if not TOKEN:
        raise RuntimeError("TOKEN env is missing (use BOT_TOKEN or TELEGRAM_TOKEN).")

    # ساخت/هماهنگ‌سازی جداول (idempotent)
    log.info("init_db() running...")
    db.init_db()
    log.info("init_db() done.")

    # ساخت اپ
    app = (
        Application.builder()
        .token(TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .rate_limiter(AIORateLimiter())          # نیازمند python-telegram-bot[rate-limiter]
        .build()
    )

    # ثبت همه هندلرها
    for h in build_handlers():
        app.add_handler(h)

    # اجرای وبهوک یا پولینگ
    if PUBLIC_URL:
        # می‌تونی در Environment کلید WEBHOOK_PATH را هم تعیین کنی (پیش‌فرض: 'webhook')
        url_path = (os.getenv("WEBHOOK_PATH") or "webhook").lstrip("/")
        full_webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"
        log.info("Starting webhook at %s", full_webhook_url)

        # PTB v20.x: از url_path و webhook_url استفاده می‌کنیم (نه path)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=full_webhook_url,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        log.warning("PUBLIC_URL not set -> running polling")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
