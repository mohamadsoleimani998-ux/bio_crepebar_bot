import os
import logging
from typing import Final

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, MessageHandler, CallbackContext,
    filters,
)

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# ---------- env ----------
BOT_TOKEN: Final[str] = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE: Final[str] = os.environ.get("WEBHOOK_BASE", "").strip().rstrip("/")
WEBHOOK_SECRET: Final[str] = os.environ.get("WEBHOOK_SECRET", "").strip()
PORT: Final[int] = int(os.environ.get("PORT", "5000"))

if not WEBHOOK_BASE:
    raise RuntimeError("WEBHOOK_BASE is not set")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is not set")

# مسیر وبهوک امن (از bot id استفاده می‌کنیم؛ توکن کامل لو نمی‌رود)
WEBHOOK_PATH: Final[str] = f"/webhook/{BOT_TOKEN.split(':', 1)[0]}"
WEBHOOK_URL: Final[str] = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"

# ---------- handlers ----------
async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    name = (user.first_name or "") if user else ""
    await update.message.reply_text(
        f"سلام {name} 👋\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."
    )

async def echo(update: Update, context: CallbackContext) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

# ---------- app ----------
def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

if __name__ == "__main__":
    app = build_app()

    log.info("Setting webhook to %s", WEBHOOK_URL)
    # وب‌سرور داخلی PTB (aiohttp) — دیگه نیازی به Flask/Gunicorn نیست
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH.lstrip("/"),
        secret_token=WEBHOOK_SECRET,
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=False,
    )
