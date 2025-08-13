import os, logging

# ---- Logging ----
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# ---- Env ----
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Env TELEGRAM_TOKEN/BOT_TOKEN is required")

DATABASE_URL = os.getenv("DATABASE_URL")  # postgres://...
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# PUBLIC_URL یا WEBHOOK_URL (هرکدوم بود استفاده می‌کنیم)
PUBLIC_URL = (
    os.getenv("WEBHOOK_URL")
    or os.getenv("PUBLIC_URL")
    or (("https://" + os.getenv("RENDER_EXTERNAL_HOSTNAME"))
        if os.getenv("RENDER_EXTERNAL_HOSTNAME") else None)
)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# ادمین‌ها (کاما جدا)
ADMIN_IDS = {int(x) for x in (os.getenv("ADMIN_IDS", "1606170079").split(",")) if x.strip()}
