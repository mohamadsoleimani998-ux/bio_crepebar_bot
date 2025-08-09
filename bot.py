# bot.py
import os
import sys
import threading
import logging
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# =========================
# Environment (لازم)
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is missing in Environment", file=sys.stderr)
    sys.exit(1)

ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.isdigit()
}
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("crepebar-bot")

# =========================
# Telegram Bot (PTB v20+)
# =========================
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("منو", callback_data="menu")],
        [InlineKeyboardButton("راهنما", callback_data="help")]
    ])

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    msg = (
        f"سلام {u.first_name} 👋\n"
        f"به بیو کِرِپ بار خوش اومدی!\n"
        f"کش‌بک فعلی: {CASHBACK_PERCENT}%\n"
        f"از دکمه‌های زیر استفاده کن:"
    )
    await update.effective_chat.send_message(msg, reply_markup=main_menu())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("دستورات:\n/start — شروع\n/help — راهنما")

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "menu":
        await q.edit_message_text("منو نمونه:\n• کرپ نوتلا — ۱۹۰\n• کرپ موز-نوتلا — ۲۲۰")
    elif q.data == "help":
        await q.edit_message_text("هر سوالی داشتی همینجا بپرس 🌟")

async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پاسخ کوتاه برای تست
    await update.message.reply_text("پیامت ثبت شد ✅")

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    # Buttons
    app.add_handler(CallbackQueryHandler(cb_handler))
    # Text fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))
    return app

def run_bot_polling():
    """
    اجرای بلاکینگِ PTB داخل ترد پس‌زمینه.
    این کار باعث می‌شود پروسه‌ی Flask (gunicorn) زنده بماند
    و خطاهای event loop / pending task رخ ندهد.
    """
    try:
        application = build_application()
        application.run_polling(
            drop_pending_updates=True,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30,
            allowed_updates=None,
        )
    except Exception as e:
        log.exception("Bot crashed: %s", e)

# ترد پس‌زمینه را استارت می‌کنیم تا همزمان با وب‌سرور اجرا شود
_bot_thread = threading.Thread(target=run_bot_polling, name="tg-bot", daemon=True)
_bot_thread.start()

# =========================
# Flask app (برای Render / health)
# =========================
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200
