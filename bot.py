# bot.py
import os
import asyncio
from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ====== Environment Vars ======
BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE = os.environ["WEBHOOK_BASE"].rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip() or None
WEBHOOK_URL = f"{WEBHOOK_BASE}/webhook/{BOT_TOKEN}"

# ====== Flask App ======
app = Flask(__name__)

# ====== ساخت اپلیکیشن تلگرام ======
application = Application.builder().token(BOT_TOKEN).updater(None).build()

# ====== دستور /start ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! 👋 ربات فعال است.")

application.add_handler(CommandHandler("start", start))

# ====== راه‌اندازی و ست کردن وبهوک ======
async def init_bot():
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

# اجرای init_bot در startup
asyncio.get_event_loop().run_until_complete(init_bot())

# ====== Route های Flask ======
@app.get("/")
def index():
    return "OK", 200

@app.post(f"/webhook/{BOT_TOKEN}")
def webhook_handler():
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return Response(status=401)

    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    asyncio.create_task(application.process_update(update))
    return Response(status=200)
