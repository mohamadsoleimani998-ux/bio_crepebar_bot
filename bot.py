import os, logging, asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import RetryAfter

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))   # Render خودش PORT می‌دهد

if not TOKEN: raise RuntimeError("BOT_TOKEN is missing")
if not WEBHOOK_URL: raise RuntimeError("WEBHOOK_URL is missing")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام 👋 ربات فعاله ✅")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("دستورات: /start /help")

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # ست وبهوک + جلوگیری از صف پیام‌های قدیمی
    try:
        await app.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        log.info("Webhook set -> %s", WEBHOOK_URL)
    except RetryAfter as e:
        log.warning("Flood control: retry after %s sec", e.retry_after)

    # سروِر داخلی PTB (پورت را Render تعیین می‌کند)
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="",              # چون کل URL را در WEBHOOK_URL داریم
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
