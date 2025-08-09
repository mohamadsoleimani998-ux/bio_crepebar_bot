# bot.py
import os
import logging
import threading
from flask import Flask, jsonify

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("crepebar-bot")

# ---------- Telegram Application ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

application = Application.builder().token(BOT_TOKEN).build()

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name if update.effective_user else "دوست"
    text = f"👋 سلام {name}\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."
    await update.message.reply_text(text)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# ---------- Background polling ----------
def run_polling():
    """
    اجرای polling در یک Thread جدا تا فرآیند وب (Flask/Gunicorn) زنده بماند.
    هیچ حلقه‌ی asyncio دستی نمی‌سازیم تا خطای event loop رخ ندهد.
    """
    try:
        logger.info("Starting Telegram polling …")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            stop_signals=None,   # اجازه می‌دهد Gunicorn خودش lifecycle را مدیریت کند
        )
    except Exception as e:
        logger.exception("Polling crashed: %s", e)

# فقط یک‌بار Thread را استارت کن
_polling_started = False
def ensure_polling_started():
    global _polling_started
    if not _polling_started:
        t = threading.Thread(target=run_polling, name="tg-polling", daemon=True)
        t.start()
        _polling_started = True

# ---------- Flask (health endpoints) ----------
app = Flask(__name__)

@app.route("/")
def root():
    return jsonify(ok=True, service="crepebar-bot")

@app.route("/healthz")
def health():
    return "ok", 200

# وقتی ماژول لود شد (توسط Gunicorn)، polling را بالا بیار
ensure_polling_started()

# برای اجرای لوکال (اختیاری)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
