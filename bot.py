import os
import threading
import asyncio
from flask import Flask, request, abort
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

# ---------- تنظیمات از Environment ----------
BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
# مسیر وبهوک را ثابت می‌کنیم تا با تغییرات بعدی به ارور نخوریم
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

# ---------- Flask (برای Gunicorn) ----------
app = Flask(__name__)

@app.get("/")
def health():
    # برای Render هِلث‌چک 200 برگردانیم
    return "OK", 200

@app.post(WEBHOOK_PATH)
def telegram_webhook():
    # اعتبارسنجی توکن مخفی (optional اما توصیه‌شده)
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)

    if not request.is_json:
        abort(400)

    update_json = request.get_json(force=True)

    # Update را ایمن از ترد Flask به لوپ بات پاس بدهیم
    update = Update.de_json(update_json, application.bot)  # type: ignore
    asyncio.run_coroutine_threadsafe(
        application.update_queue.put(update), bot_loop
    )
    return "OK", 200

# ---------- Telegram Bot (python-telegram-bot v20) ----------
application: Application
bot_loop: asyncio.AbstractEventLoop

# هندلرها
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name if update.effective_user else "دوست عزیز"
    text = (
        f"سلام {name} 👋\n"
        "ربات فعاله. برای تست، هر متنی بفرست تا برگردونم."
    )
    await update.message.reply_text(text)  # type: ignore

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

def build_application() -> Application:
    app_ = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    app_.add_handler(CommandHandler("start", cmd_start))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app_

# اجرای امنِ PTB در یک تردِ جدا با event loop اختصاصی
def start_bot_worker():
    global application, bot_loop

    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)

    application = build_application()

    async def runner():
        # initialize/start و ست‌کردن وبهوک روی URL پایدار
        await application.initialize()
        await application.start()

        full_webhook_url = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"
        # drop_pending_updates=True برای جلوگیری از سیل پیام‌های قدیمی
        await application.bot.set_webhook(
            url=full_webhook_url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )

        # آماده پردازش آپدیت‌هایی که از Flask می‌رسند
        # application.start() صف را مصرف می‌کند، فقط لوپ را زنده نگه داریم
        # (run_forever در بیرون صدا زده می‌شود)
        return

    bot_loop.create_task(runner())
    bot_loop.run_forever()

# تردِ بات را در زمان import بالا می‌آوریم (با gunicorn سازگار)
_bot_thread = threading.Thread(target=start_bot_worker, daemon=True, name="ptb-worker")
_bot_thread.start()

# شات‌داون تمیز هنگام خاموش‌شدن پاد
def _shutdown():
    if "application" in globals():
        fut = asyncio.run_coroutine_threadsafe(application.stop(), bot_loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        bot_loop.call_soon_threadsafe(bot_loop.stop)

import atexit
atexit.register(_shutdown)
