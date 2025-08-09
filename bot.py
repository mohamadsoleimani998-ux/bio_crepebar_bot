# bot.py
import os
import asyncio
import threading

from flask import Flask, request, abort
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ======= ENV =======
BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
PORT = int(os.environ.get("PORT", "5000"))

# آدرس نهایی وبهوک (به /webhook ختم می‌شود)
WEBHOOK_URL = f"{WEBHOOK_BASE}/webhook" if WEBHOOK_BASE else None

# ======= Telegram App =======
application = Application.builder().token(BOT_TOKEN).build()

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعاله ✅")

application.add_handler(CommandHandler("start", start_cmd))

# ======= Flask (WSGI) =======
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

@app.post("/webhook")
def telegram_webhook():
    # تطابق سکرت برای امنیت
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        abort(401)

    data = request.get_json(force=True, silent=False)
    update = Update.de_json(data, application.bot)

    # پردازش آپدیت داخل حلقه‌ی asyncio پس‌زمینه
    fut = asyncio.run_coroutine_threadsafe(
        application.process_update(update), _LOOP
    )
    # اگر خطایی در coroutine رخ دهد، در لاگ بالا می‌آید
    try:
        fut.result(timeout=10)
    except Exception:
        # اجازه می‌دهیم Gunicorn خطا را لاگ کند
        pass
    return "OK", 200

# ======= Background asyncio loop just for PTB processing =======
def _run_event_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())

    # ست‌کردن وبهوک یکبار پس از شروع
    async def _ensure_webhook():
        if WEBHOOK_URL:
            await application.bot.set_webhook(
                url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET
            )
    loop.run_until_complete(_ensure_webhook())

    loop.run_forever()

_LOOP = asyncio.new_event_loop()
threading.Thread(target=_run_event_loop, args=(_LOOP,), daemon=True).start()
