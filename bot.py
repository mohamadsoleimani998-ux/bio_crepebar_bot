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
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify(status="ok", service="crepebar-bot")

@app.route("/health")
def health():
    return "OK", 200

# Run Telegram polling in same event loop
@app.before_first_request
def activate_bot():
    loop = asyncio.get_event_loop()
    tg_app = build_application()
    loop.create_task(tg_app.run_polling(drop_pending_updates=True))
    log.info("Telegram polling started.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
