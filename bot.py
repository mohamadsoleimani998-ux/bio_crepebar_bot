import os
import threading
import asyncio
import logging
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ===== Logging =====
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# ===== Config =====
BOT_TOKEN = os.environ["BOT_TOKEN"]  # توی Environment از قبل داری

# ===== Handlers =====
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات فعال است ✅")

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    return app

# ===== Polling runner (background thread) =====
def run_polling():
    application = build_application()
    asyncio.run(application.run_polling(drop_pending_updates=True))

# ===== Flask app (stays alive for Render) =====
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify(status="ok", service="crepebar-bot")

@app.route("/health")
def health():
    return "OK", 200

# Start Telegram polling in background
threading.Thread(target=run_polling, daemon=True).start()
log.info("Background polling started.")
