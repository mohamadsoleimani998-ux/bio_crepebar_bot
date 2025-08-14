import os
import logging

# ------------------ ENV ------------------
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip() or None
PORT = int(os.getenv("PORT", "8080"))

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")

# ادمین‌ها: لیست عددی
def _parse_admin_ids(v: str | None):
    if not v:
        return []
    out = []
    for p in v.replace(";", ",").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            pass
    return out

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS"))

# واحد پول
CURRENCY = "تومان"

# ------------------ LOG ------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar")

# ------------------ Helpers ------------------
def is_admin(tg_id: int) -> bool:
    return int(tg_id) in ADMIN_IDS

def fmt_money(amount: float | int) -> str:
    try:
        n = int(round(float(amount)))
    except Exception:
        n = 0
    s = f"{n:,}".replace(",", "،")
    return f"{s} {CURRENCY}"

# کارت به کارت (نمایش در صفحه شارژ)
CARD_PAN  = os.getenv("CARD_PAN", "---- ---- ---- ----")
CARD_NAME = os.getenv("CARD_NAME", "صاحب حساب")
CARD_NOTE = os.getenv("CARD_NOTE", "لطفاً بعد از واریز، رسید را ارسال کنید.")
