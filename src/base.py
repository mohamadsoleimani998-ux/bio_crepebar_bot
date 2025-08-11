import os

def env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Required env var {name} is not set")
    return val

# توکن را از TELEGRAM_TOKEN یا BOT_TOKEN بردار
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")

# آدرس پابلیک (برای وب‌هوک)
PUBLIC_URL = os.getenv("WEBHOOK_URL") or os.getenv("WEBHOOK_BASE") or os.getenv("PUBLIC_URL") or ""

# سِکرت وب‌هوک (اختیاری ولی بهتر است داشته باشی)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")

# پورت سرویس روی Render
PORT = int(os.getenv("PORT", "5000"))

# درصد کش‌بک
try:
    CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "0"))
except ValueError:
    CASHBACK_PERCENT = 0

# ادمین‌ها (با کاما یا فاصله)
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set()
for x in _admin_raw.replace(",", " ").split():
    if x.isdigit():
        ADMIN_IDS.add(int(x))

DATABASE_URL = env("DATABASE_URL")
