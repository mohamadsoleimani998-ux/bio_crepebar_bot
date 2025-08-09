import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import RetryAfter

# -------- Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# -------- Env
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN env var is missing")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL env var is missing")

# -------- Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام 👋 ربات کرپ‌بار فعاله ✅")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("دستورات:\n/start\n/help")

# -------- Main
async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # تلاش برای ست‌کردن وبهوک (اگر چندبار پشت‌سرهم صدا شد، Flood کنترل می‌شود)
    try:
        await app.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        log.info("Webhook set ✅ -> %s", WEBHOOK_URL)
    except RetryAfter as e:
        log.warning("Flood control: retry after %s sec. ادامه بدون set_webhook مجدد.", e.retry_after)

    # روی پورتی که Render می‌دهد گوش می‌کنیم
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path="",            # چون WEBHOOK_URL کامل است
        webhook_url=WEBHOOK_URL # آدرس کامل وبهوک
    )

if __name__ == "__main__":
    asyncio.run(main())
