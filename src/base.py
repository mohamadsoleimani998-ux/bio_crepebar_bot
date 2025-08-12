import os
import logging

# --- Logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# --- Env ---
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
PUBLIC_URL = (os.getenv("WEBHOOK_URL") or os.getenv("PUBLIC_URL") or "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# Admin ids: comma/space separated
def _parse_admins(val: str):
    if not val:
        return set()
    parts = []
    for ch in [",", " ", ";", "|"]:
        if ch in val:
            parts = [p for p in val.replace(ch, " ").split() if p]
    if not parts:
        parts = [val]
    try:
        return {int(p) for p in parts}
    except Exception:
        return set()

ADMIN_IDS = _parse_admins(os.getenv("ADMIN_IDS", ""))

CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower())
if not TOKEN:
    log.error("TOKEN is missing. Set TELEGRAM_TOKEN or BOT_TOKEN env")

# Static data
CARD_NUMBER = "5029081080984145"   # برای شارژ کیف پول (کارت به کارت)
