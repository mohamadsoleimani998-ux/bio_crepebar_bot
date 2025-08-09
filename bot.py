import os
import logging
import signal
import threading
import asyncio
from flask import Flask, jsonify

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# -------------------- Logging --------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# -------------------- Config --------------------
# فقط از همین توکن استفاده می‌کنیم (Environment را تغییر نده)
BOT_TOKEN = os.environ["BOT_TOKEN"]

# -------------------- Telegram Handlers --------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پاسخ ساده برای اطمینان از کارکرد ربات"""
    text = (
        "سلام! 👋\n"
        "ربات فعال است. این پیام تست است تا مطمئن شویم دیپلوی سالمه.\n"
        "می‌تونم بعداً منو/سفارش و ... رو هم اضافه کنم."
    )
    await update.message.reply_text(text)

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    return app

# -------------------- Polling in background --------------------
_stop_event = threading.Event()
_tg_thread: threading.Thread | None = None

def _run_polling_bg(app: Application) -> None:
    """
    اجرای تمیز polling در یک event loop مخصوص thread
    تا بتوانیم shutdown بدون warning داشته باشیم.
    """
    async def _main():
        await app.initialize()
        await app.start()
        # در PTB v20، Updater به صورت داخلی ساخته می‌شود:
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram polling started.")
        # صبر تا سیگنال توقف
        while not _stop_event.is_set():
            await asyncio.sleep(0.5)
        # توقف تمیز
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        log.info("Telegram polling stopped cleanly.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

def start_polling_once() -> None:
    global _tg_thread
    if _tg_thread is not None and _tg_thread.is_alive():
        return
    application = build_application()
    _tg_thread = threading.Thread(
        target=_run_polling_bg, args=(application,), name="telegram-polling", daemon=True
        )
    _tg_thread.start()
    log.info("Background polling thread started.")

def _handle_sigterm(*_):
    # سیگنال توقف از Render/Gunicorn
    log.info("SIGTERM received. Stopping polling ...")
    _stop_event.set()

# سیگنال‌ها برای خاموشی تمیز
signal.signal(signal.SIGTERM, _handle_sigterm)
try:
    signal.signal(signal.SIGINT, _handle_sigterm)
except Exception:
    pass

# -------------------- Flask HTTP (health) --------------------
app = Flask(__name__)

@app.get("/")
def root():
    return jsonify(status="ok", service="bio-crepebar-bot"), 200

@app.get("/health")
def health():
    return "OK", 200

# وقتی ماژول لود شد (در gunicorn)، polling را یک بار روشن کن
start_polling_once()
