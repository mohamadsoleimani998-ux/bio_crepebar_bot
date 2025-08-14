# src/bot.py
import os
import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# --- ماژول‌های خود پروژه
# build_handlers(app: Application) باید همه‌ی هندلرها را روی app ست کند
from .handlers import build_handlers
from .db import init_db

# -------------------------
# تنظیم لاگر ساده (اگر base.log دارید هم مشکلی نیست)
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")

# -------------------------
# متغیرهای محیطی
# -------------------------
BOT_TOKEN: str = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or ""
PUBLIC_URL: Optional[str] = os.environ.get("PUBLIC_URL") or os.environ.get("WEBHOOK_URL")
WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT: int = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is missing.")

# -------------------------
# /start: پیام خیلی ساده (هندلرهای اصلی در handlers.py است)
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(
        "سلام 😊\nربات فروشگاهی شما آماده است!",
        parse_mode=ParseMode.HTML
    )

# -------------------------
# main
# -------------------------
def main() -> None:
    log.info("init_db() …")
    init_db()
    log.info("init_db() done.")

    app = Application.builder().token(BOT_TOKEN).build()

    # یک استارت ساده؛ بقیه‌ی منو/ادمین/کیف‌پول داخل build_handlers اضافه می‌شود
    app.add_handler(CommandHandler("start", cmd_start))

    # همه‌ی هندلرهای تخصصی پروژه (دسته‌ها، سفارش، کیف پول، ادمین و …)
    build_handlers(app)

    # --- اجرای بات: Webhook اگر PUBLIC_URL باشد، وگرنه Polling
    if PUBLIC_URL:
        # آدرس نهایی وبهوک: https://your-domain/<WEBHOOK_SECRET>
        webhook_path = f"/{WEBHOOK_SECRET}"
        webhook_url = PUBLIC_URL.rstrip("/") + webhook_path

        log.info("Starting webhook …")
        log.info("listen=0.0.0.0 port=%s path=%s url=%s", PORT, webhook_path, webhook_url)

        # توجه: در PTB 21.4 پارامترها همین‌ها هستند و webhhok_path نداریم
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_SECRET,
            webhook_url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:
        log.info("PUBLIC_URL not set → starting polling …")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
