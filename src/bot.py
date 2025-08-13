import asyncio
import os

from telegram.ext import Application
from .base import log, BOT_TOKEN, WEBHOOK_SECRET, PORT, BASE_URL
from . import db
from .handlers import build_handlers

def ensure_envs():
    missing = []
    for key in ("BOT_TOKEN","DATABASE_URL"):
        if not os.environ.get(key) and key=="DATABASE_URL" and not os.environ.get("DB_URL"):
            missing.append(key)
        elif not os.environ.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Missing envs: {', '.join(missing)}")
    if not BASE_URL:
        raise RuntimeError("BASE_URL/RENDER_EXTERNAL_URL is required for webhooks")

def main():
    ensure_envs()
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # handlers
    for h in build_handlers():
        app.add_handler(h)

    # webhook
    path = f"/tg/{WEBHOOK_SECRET}"
    url = BASE_URL.rstrip("/") + path
    log.info("Setting webhook to %s", url)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        secret_token=WEBHOOK_SECRET,
        webhook_url=url,
    )

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("FATAL: bot crashed during startup")
        raise
