# handlers.py
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

START_TEXT = "👋 سلام\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # هر چی بفرسته، همونو برگردون
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
