# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from telegram.ext import Application, AIORateLimiter
from .base import log, BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_SECRET, PUBLIC_URL
from . import db
from .handlers import build_handlers

async def on_error(update, context):
    log.exception("Unhandled error", exc_info=context.error)

def main():
    db.init_db()

    app = Application.builder() \
        .token(BOT_TOKEN) \
        .rate_limiter(AIORateLimiter()) \
        .build()

    app.add_error_handler(on_error)
    build_handlers(app)

    if WEBHOOK_URL:
        log.info("Starting webhook at %s", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=10000,
            secret_token=WEBHOOK_SECRET,
            webhook_url=WEBHOOK_URL,
            path=WEBHOOK_PATH,
        )
    else:
        log.info("Starting polling...")
        app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
