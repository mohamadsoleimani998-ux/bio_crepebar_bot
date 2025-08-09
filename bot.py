# --- Debug-friendly bot.py (safe to drop-in) ---
import os, sys, traceback, logging
from datetime import datetime

# لاگ‌گیری واضح روی stdout (Render دقیقاً همین رو نشان می‌دهد)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("bio-crepebar-bot")

def _safe(val, keep=4):
    """برای جلوگیری از نمایش کامل مقادیر حساس در لاگ"""
    if not val:
        return "<empty>"
    return f"{val[:keep]}...{val[-keep:]}" if len(val) > keep*2 else "***"

def print_boot_info():
    log.info("==== Booting bot ====")
    log.info("Python: %s", sys.version.split()[0])
    log.info("TZ: %s", os.environ.get("TZ", "not-set"))
    log.info("ENV keys: %s", ", ".join(sorted(os.environ.keys())))
    log.info("BOT_TOKEN: %s", _safe(os.environ.get("BOT_TOKEN")))
    log.info("WEBHOOK_BASE: %s", os.environ.get("WEBHOOK_BASE", "<unset>"))
    log.info("DATABASE_URL set? %s", bool(os.environ.get("DATABASE_URL")))
    log.info("Cashback: %s", os.environ.get("CASHBACK_PERCENT", "<unset>"))

# ====== از اینجا کد تلگرام شما ======
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]  # اگر ست نباشد KeyError می‌دهد و پایین try/except می‌گیریمش

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعال است ✅")

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    return app
# ====== پایان بخش اصلی ربات ======

async def _run():
    """
    اگر WEBHOOK_BASE ست باشد، همون webhook فعلی را می‌گذاریم.
    اگر نبود، می‌رویم سراغ polling. (رفتار را خراب نمی‌کند—فقط طبق ENV تصمیم می‌گیرد)
    """
    print_boot_info()
    app = build_app()

    webhook_base = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
    secret_token = os.environ.get("WEBHOOK_SECRET", "crepe-secret")

    if webhook_base:
        # همان مسیری که داشتیم
        path = f"/webhook/{secret_token}"
        full = f"{webhook_base}{path}"
        log.info("Starting in WEBHOOK mode → %s", full)
        await app.bot.set_webhook(url=full, secret_token=secret_token)
        # run_webhook بدون Flask (PTB v20) → Render فقط به پورت نیاز ندارد
        await app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            webhook_url=full,
            secret_token=secret_token
        )
    else:
        log.info("Starting in POLLING mode")
        await app.run_polling(allowed_updates=None, close_loop=False)

if __name__ == "__main__":
    try:
        import asyncio
        log.info("Process started at %s", datetime.utcnow().isoformat() + "Z")
        asyncio.run(_run())
    except KeyError as e:
        # معمول‌ترین خطا: نبودن یک ENV (مثل WEBHOOK_BASE یا BOT_TOKEN)
        log.error("ENV missing: %s", e)
        log.error("Tip: مقدار %s را در Environment ست کن.", str(e))
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        # هر خطای غیرمنتظره را کامل لاگ کن تا در Render ببینیم
        log.exception("Fatal error in main: %s", e)
        traceback.print_exc()
        sys.exit(1)
