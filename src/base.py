import logging, os

# ---------- logging ----------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL","INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")

# ---------- env / constants ----------
BOT_TOKEN       = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
DATABASE_URL    = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL")
PUBLIC_URL      = (os.environ.get("WEBHOOK_URL") or
                   os.environ.get("WEBHOOK_BASE") or
                   os.environ.get("PUBLIC_URL") or "")
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET","T3legramWebhookSecret_2025")
CASHBACK_PERCENT= float(os.environ.get("CASHBACK_PERCENT","3"))
ADMIN_IDS       = [int(x) for x in (os.environ.get("ADMIN_IDS","").replace(" ","") or "").split(",") if x]

CURRENCY = "تومان"

# sanity
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL/WEBHOOK_URL is missing")
