import os
import threading
import asyncio
import logging
import json
from typing import List

import requests
from flask import Flask, request, abort

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ------------------ Config & Logging ------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE") or os.environ.get("WEBHOOK_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")

# برای راحتی، ادمین‌ها اختیاری است
def _parse_admin_ids(v: str) -> List[int]:
    try:
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    except Exception:
        return []

ADMIN_IDS = _parse_admin_ids(os.environ.get("ADMIN_IDS", ""))

# ------------------ Telegram App ------------------
application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = "سلام 👋\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."
    await update.effective_message.reply_text(text)

# یک echo ساده برای تست
async def echo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

application.add_handler(CommandHandler("start", start_cmd))
# handler ساده برای هر پیام متنی
from telegram.ext import MessageHandler, filters
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# ------------------ Async loop in background ------------------
# نکته‌ی کلیدی: لوپ مستقل می‌سازیم و داخل یک ترد اجرا می‌کنیم تا
# از ارور «There is no current event loop in thread …» جلوگیری شود.
_loop = asyncio.new_event_loop()

def _run_app_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(application.initialize())
    _loop.run_until_complete(application.start())
    log.info("telegram application started")
    _loop.run_forever()

_bg = threading.Thread(target=_run_app_loop, name="tg-app-loop", daemon=True)
_bg.start()

# ------------------ Webhook setup ------------------
def _set_webhook_once():
    """
    وبهوک را با آدرس ثابت ست می‌کند. این تابع سنکرون است و ساختار فعلی را به‌هم نمی‌زند.
    """
    if not WEBHOOK_BASE:
        log.warning("WEBHOOK_BASE/WEBHOOK_URL is not set; webhook not configured.")
        return
    base = WEBHOOK_BASE.rstrip("/")
    hook_url = f"{base}/{BOT_TOKEN}/{WEBHOOK_SECRET}"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            data={
                "url": hook_url,
                "secret_token": WEBHOOK_SECRET,
                "drop_pending_updates": "true",
            },
            timeout=10,
        )
        ok = False
        try:
            j = resp.json()
            ok = j.get("ok", False)
            log.info("setWebhook response: %s", j)
        except Exception:
            log.info("setWebhook status=%s, body=%s", resp.status_code, resp.text[:200])
        if not ok:
            log.warning("setWebhook may not be ok; check token/url/secret.")
    except Exception as e:
        log.exception("failed to set webhook: %s", e)

_set_webhook_once()

# ------------------ Flask (health + webhook endpoint) ------------------
app = Flask(__name__)

@app.get("/")
def health():
    # برای هلت‌چک Render
    return "OK", 200

@app.post(f"/{BOT_TOKEN}/{WEBHOOK_SECRET}")
def telegram_webhook():
    # ولیدیشن سکرت هدر (اختیاری ولی امن‌تر)
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)

    try:
        data = request.get_json(force=True, silent=False)
        update = Update.de_json(data, application.bot)
        # IMPORTANT: چون در ترد Flask هستیم، باید از run_coroutine_threadsafe استفاده کنیم
        fut = asyncio.run_coroutine_threadsafe(
            application.update_queue.put(update), _loop
        )
        fut.result(timeout=5)  # خطایی بود همان‌جا بگیرد
    except Exception as e:
        log.exception("webhook error: %s", e)
        return "ERROR", 500

    return "OK", 200

# ------------------ gunicorn entry ------------------
# Procfile شما:  web: gunicorn bot:app
# بنابراین نیازی به __main__ نیست؛ ولی برای اجرای لوکال می‌گذاریم:
if __name__ == "__main__":
    # اجرای لوکال (در Render gunicorn اجرا می‌کند)
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
