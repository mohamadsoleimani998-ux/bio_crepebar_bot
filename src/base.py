# src/base.py
import os
import logging

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | crepebar | %(message)s"
)
log = logging.getLogger("crepebar")

# --- ENV / Config ---
BOT_TOKEN     = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
PUBLIC_URL    = os.getenv("PUBLIC_URL", "").rstrip("/")
DATABASE_URL  = os.getenv("DATABASE_URL")
WEBHOOK_SECRET= os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT          = int(os.getenv("PORT", "8000"))

# Admins (comma/space separated)
ADMIN_IDS = []
for part in (os.getenv("ADMIN_IDS") or "").replace(",", " ").split():
    if part.strip().isdigit():
        ADMIN_IDS.append(int(part.strip()))

def is_admin(tg_id: int) -> bool:
    return int(tg_id) in ADMIN_IDS

# Money / currency
CURRENCY = "تومان"
def fmt_money(x: float|int) -> str:
    try:
        v = int(round(float(x)))
    except Exception:
        v = 0
    return f"{v:,} {CURRENCY}".replace(",", "٬")

# Card to card (fill from user message)
CARD_PAN  = "5029081080984145"
CARD_NAME = "شهرزاد محمد زاده"
CARD_NOTE = "پس از کارت‌به‌کارت، رسید را در «کیف پول» ارسال کنید."

# Instagram
INSTAGRAM_URL = "https://www.instagram.com/bio.crepebar?igsh=MXN1cnljZTN3NGhtZw=="
