import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN".lower())
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE") or os.getenv("WEBHOOK_URL")  # مثل https://bio_crepebar_bot.onrender.com
PORT = int(os.getenv("PORT", "8000"))  # Render خودش PORT رو ست می‌کند
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # اختیاری

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN (یا TELEGRAM_TOKEN) تنظیم نشده")
if not WEBHOOK_BASE:
    raise RuntimeError("WEBHOOK_BASE/WEBHOOK_URL تنظیم نشده (مثلاً https://xxx.onrender.com)")

# مسیر کامل وبهوک: BASE + /webhook/<token>
WEBHOOK_BASE = WEBHOOK_BASE.rstrip("/")
WEBHOOK_PATH = f"webhook/{BOT_TOKEN}"
FULL_WEBHOOK_URL = f"{WEBHOOK_BASE}/{WEBHOOK_PATH}"

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# ---------- handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات فعاله ✅")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start - شروع\n/help - راهنما")

# ---------- main ----------
async def main():
    # Application جایگزین Updater در v20+
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # وبهوک را ست می‌کنیم (پیام‌های معطل‌مانده هم پاک می‌شود تا Flood نخوریم)
    await app.bot.set_webhook(
        url=FULL_WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )

    # سرور داخلی aiohttp را بالا می‌آورد (نیازی به Flask/Gunicorn نیست)
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET or None,
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
