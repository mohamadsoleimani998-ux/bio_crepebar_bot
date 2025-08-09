# bot.py
import os
import logging
import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# ---------- Env ----------
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # مثلا: https://bio_crepebar_bot.onrender.com/

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL is not set (e.g. https://<your-service>.onrender.com/)")

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام 👋 ربات آماده‌ست و با وبهوک کار می‌کنه ✅")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("دستورات: /start , /help")

# ---------- Main ----------
async def main():
    app = Application.builder().token(TOKEN).build()

    # ثبت دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # ست‌کردن وبهوک روی URL سرویس Render
    await app.bot.set_webhook(url=WEBHOOK_URL)

    # اجرای وب‌سرور داخلی PTB برای دریافت وبهوک
    # نکته: url_path باید با همون مسیری که در WEBHOOK_URL هست یکی باشه.
    # ما توصیه می‌کنیم WEBHOOK_URL را با اسلش پایانی تنظیم کنید و اینجا url_path="" بگذارید.
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path="",               # روت "/"
        webhook_url=WEBHOOK_URL,   # باید دقیقا برابر مقدار set_webhook باشد
        stop_signals=None,         # اجازه می‌دهد روی Render به آرامی اجرا بماند
    )

if __name__ == "__main__":
    # فقط یکبار لوپ راه می‌افتد؛ ارور "Cannot close a running event loop" و
    # "Task was destroyed but it is pending" دیگر پیش نمی‌آید.
    asyncio.run(main())
