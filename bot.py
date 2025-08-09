import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask, request

# خواندن متغیرهای محیطی
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", 0))
DATABASE_URL = os.environ.get("DATABASE_URL")
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# ساخت اپلیکیشن Flask
app = Flask(__name__)

# ساخت اپلیکیشن تلگرام
application = ApplicationBuilder().token(BOT_TOKEN).build()

# فرمان /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"سلام 👋 خوش آمدید!\nکش‌بک شما: {CASHBACK_PERCENT}%")

# اضافه کردن هندلرها
application.add_handler(CommandHandler("start", start))

# مسیر وبهوک
@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

# اجرای سرور
if __name__ == "__main__":
    # ست کردن وبهوک
    application.bot.set_webhook(url=f"{WEBHOOK_URL}/{WEBHOOK_SECRET}")
    # اجرای Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
