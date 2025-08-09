import os
import asyncio
import logging
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Telegram handler
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات فعال است ✅")

def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    return app

# Flask app
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return jsonify(status="ok", service="crepebar-bot")

@flask_app.route("/health")
def health():
    return "OK", 200

# اجرای همزمان Flask و Telegram Polling
async def run_telegram():
    tg_app = build_application()
    await tg_app.run_polling(drop_pending_updates=True)

def start_services():
    loop = asyncio.get_event_loop()
    loop.create_task(run_telegram())
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    start_services()
