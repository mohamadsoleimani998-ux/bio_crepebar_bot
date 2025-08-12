from telegram.ext import Application, Defaults
from telegram.constants import ParseMode
from .base import TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT, log
from .handlers import build_handlers
from . import db

def main():
    if not TOKEN:
        raise RuntimeError("TOKEN env is missing (TELEGRAM_TOKEN / BOT_TOKEN).")

    # ساخت/به‌روزرسانی جداول
    db.init_db()

    app = Application.builder().token(TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()

    # جلوگیری از «هیچ هندلری ثبت نشده» و اطمینان از ثبت /start
    for h in build_handlers():
        app.add_handler(h)

    # هندلر خطا برای جلوگیری از خاموشی ساکت
    async def on_error(update, context):
        log.exception("Unhandled error", exc_info=context.error)
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text("❌ خطای غیرمنتظره. لطفاً دوباره تلاش کنید.")
        except Exception:
            pass
    app.add_error_handler(on_error)

    if PUBLIC_URL:
        url = PUBLIC_URL.rstrip("/") + f"/{TOKEN}"
        log.info("Running webhook at %s", url)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:
        log.warning("PUBLIC_URL not set -> running polling")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
