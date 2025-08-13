import os
import logging

# -------- Env
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PUBLIC_URL = os.getenv("PUBLIC_URL") or os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "Te1egramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# Admins: comma/space separated Telegram ids
def _parse_admins(val: str | None):
    if not val:
        return set()
    parts = [p.strip() for p in val.replace(",", " ").split()]
    return {int(p) for p in parts if p.isdigit()}

ADMIN_IDS = _parse_admins(os.getenv("ADMIN_IDS"))

# Optional default cashback percent shown in پیام‌ها؛
# محاسبه واقعی از جدول settings انجام می‌شود.
DEFAULT_CASHBACK = int(os.getenv("CASHBACK_PERCENT", "3"))

# -------- Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")
