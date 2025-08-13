import logging
import os

from dotenv import load_dotenv
load_dotenv()

# ---------- Log ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | crepebar | %(message)s"
)
log = logging.getLogger("crepebar")

# ---------- ENV ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/") + "/"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
CASHBACK_PERCENT = float(os.environ.get("CASHBACK_PERCENT", "3") or 3)

_admin_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admin_raw.replace(",", " ").split() if x.isdigit()}

CURRENCY = "تومان"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS
