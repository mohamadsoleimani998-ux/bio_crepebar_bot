import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = Flask(__name__)

# ایجاد برنامه بات
application = Application.builder().token(TOKEN).build()

# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! بات شما با موفقیت اجرا شد ✅")

application.add_handler(CommandHandler("start", start))

# مسیر وبهوک
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

if __name__ == "__main__":
    # ست کردن وبهوک
    application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    # اجرای Flask روی Render
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
