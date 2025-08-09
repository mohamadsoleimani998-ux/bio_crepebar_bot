import os
import asyncio
from flask import Flask, request, jsonify, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# ====== Env ======
BOT_TOKEN       = os.environ["BOT_TOKEN"]
WEBHOOK_BASE    = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET")  # اختیاری
PORT            = int(os.environ.get("PORT", "10000"))  # Render هر پورتی را قبول می‌کند

# URL نهایی وبهوک: https://.../webhook/<token>
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{WEBHOOK_BASE}{WEBHOOK_PATH}" if WEBHOOK_BASE else None

# ====== Telegram application ======
application = Application.builder().token(BOT_TOKEN).build()

async def cmd_start(update: Update, _):
    await update.message.reply_text("سلام 👋 ربات فعاله. برای تست، هر متنی بفرست تا برگردونم.")

async def echo(update: Update, _):
    if update.message:
        await update.message.reply_text(update.message.text)

application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# ====== Flask app ======
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

@app.post(WEBHOOK_PATH)
def telegram_webhook():
    # اگر Secret تعریف شده، هدر تلگرام را چک کن
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return Response(status=401)

    data = request.get_json(force=True, silent=True)
    if not data:
        return Response(status=400)

    update = Update.de_json(data, application.bot)
    # پردازش آپدیت را به حلقه رویداد بده
    application.create_task(application.process_update(update))
    return Response(status=200)

# ====== lifecycle: initialize/start و setWebhook یک‌بار ======
_app_started = False
async def _startup_once():
    global _app_started
    if _app_started:
        return
    await application.initialize()
    await application.start()
    # ست کردن وبهوک روی مسیر ثابت (idempotent)
    if WEBHOOK_URL:
        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET  # اگر None باشد تلگرام هدر نمی‌فرستد
        )
    _app_started = True

# در اولین درخواست یا اولین import، app را بالا بیاور
# (Flask 3 دیگر before_first_request ندارد؛ این روش امن است)
@app.before_request
def ensure_started():
    if not _app_started:
        asyncio.get_event_loop().create_task(_startup_once())

# خروج تمیز (برای ری‌دیپلوی‌های Render)
@app.route("/shutdown-hook", methods=["POST"])
def shutdown_hook():
    try:
        asyncio.get_event_loop().create_task(application.stop())
        asyncio.get_event_loop().create_task(application.shutdown())
    finally:
        return jsonify(ok=True)

# برای Gunicorn: bot:app
if __name__ == "__main__":
    # اجرای لوکال
    asyncio.get_event_loop().create_task(_startup_once())
    app.run(host="0.0.0.0", port=PORT)
