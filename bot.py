# bot.py
import os
import json
import threading
import asyncio
from flask import Flask, request, Response

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ====== تنظیمات از Environment ======
BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE = os.environ["WEBHOOK_BASE"].rstrip("/")  # مثل: https://bio-crepebar-bot.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip() or None
WEBHOOK_URL = f"{WEBHOOK_BASE}/webhook/{BOT_TOKEN}"

# ====== Flask (برای Gunicorn) ======
app = Flask(__name__)

# ====== حلقه‌ی جداگانه برای PTB ======
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()

def run_async(coro):
    """اجرا کردن کوروتین روی حلقه‌ی پس‌زمینه، بدون بستن event loop اصلی."""
    return asyncio.run_coroutine_threadsafe(coro, _loop)

# ====== ساخت اپلیکیشن تلگرام ======
application = Application.builder().token(BOT_TOKEN).build()

# ------- Handlers -------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! 👋 ربات فعاله.")

application.add_handler(CommandHandler("start", start))

# ====== راه‌اندازی PTB و ست کردن وبهوک ======
async def _startup():
    # ترتیب مهم است
    await application.initialize()
    await application.start()
    # ست وبهوک (اگر از قبل چیزی بود، جایگزین می‌شود)
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

# اجرای استارتاپ روی حلقه پس‌زمینه
run_async(_startup()).result()

# ====== روت‌های وبهوک و سلامت ======
@app.get("/")
def root():
    return "OK", 200

@app.post(f"/webhook/{BOT_TOKEN}")
def telegram_webhook():
    # اگر Secret تعریف شده، هدر تلگرام را بررسی کن
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return Response(status=401)

    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        return Response(status=400)

    # ساخت Update و پردازش توسط PTB
    try:
        update = Update.de_json(data, application.bot)
        run_async(application.process_update(update))
    except Exception:
        return Response(status=500)

    return Response(status=200)
