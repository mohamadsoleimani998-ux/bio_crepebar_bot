import logging
import os
from dotenv import load_dotenv

load_dotenv()

# ---- logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")

# ---- ENV
BOT_TOKEN        = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DATABASE_URL     = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
PUBLIC_URL       = (os.getenv("PUBLIC_URL") or os.getenv("WEBHOOK_BASE") or "").rstrip("/")
WEBHOOK_SECRET   = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
CASHBACK_PERCENT = float(os.getenv("CASHBACK_PERCENT", "3") or 0)

# admin ids: "111,222"
_admin_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = {int(x) for x in _admin_raw.replace(" ", "").split(",") if x.isdigit()}

def tman(amount) -> str:
    """Format TOMAN with thousands separator."""
    try:
        v = int(round(float(amount)))
    except Exception:
        v = 0
    return f"{v:,} تومان"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS
