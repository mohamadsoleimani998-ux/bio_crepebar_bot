import os
import logging

# ---- Env ----
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower())
PUBLIC_URL = os.getenv("WEBHOOK_URL") or os.getenv("PUBLIC_URL")  # Render public URL
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# Admins: comma/space separated
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admin_raw.replace(",", " ").split() if x.isdigit()}

CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")
