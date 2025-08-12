import logging, os

# ── تنظیم لاگ ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# ── ENV ها ───────────────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower()) or ""
PUBLIC_URL = (os.getenv("WEBHOOK_URL") or os.getenv("PUBLIC_URL") or "").strip()
WEBHOOK_BASE = (os.getenv("WEBHOOK_BASE") or PUBLIC_URL).strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or "Secret_123"
PORT = int(os.getenv("PORT") or "10000")

# ادمین‌ها: شناسه‌ها با کاما
_admin_env = os.getenv("ADMIN_IDS", "").replace(" ", "")
ADMIN_IDS = {int(x) for x in _admin_env.split(",") if x.isdigit()}

CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT") or "3")  # درصد
CARD_NUMBER = os.getenv("CARD_NUMBER") or "5029081080984145"  # کارت شارژ

if not TOKEN:
    raise RuntimeError("TOKEN env is missing (TELEGRAM_TOKEN / BOT_TOKEN).")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing.")
