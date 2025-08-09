import os, logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN".lower())
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE") or os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8000"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده")
if not WEBHOOK_BASE:
    raise RuntimeError("WEBHOOK_BASE/WEBHOOK_URL تنظیم نشده")

WEBHOOK_BASE = WEBHOOK_BASE.rstrip("/")
WEBHOOK_PATH = f"webhook/{BOT_TOKEN}"
FULL_WEBHOOK_URL = f"{WEBHOOK_BASE}/{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("crepebar-bot")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات فعاله ✅")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start - شروع\n/help - راهنما")

async def main():
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    await app.bot.set_webhook(
        url=FULL_WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET or None,
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
