# -*- coding: utf-8 -*-
import os
import logging

# ---------- Logging ----------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# ---------- Env & constants ----------
# Bot/Webhook
TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
PORT = int(os.getenv("PORT", "10000"))

# DB / Settings
DATABASE_URL = os.getenv("DATABASE_URL", "")
try:
    CASHBACK_PERCENT = float(os.getenv("CASHBACK_PERCENT", "3"))
except Exception:
    CASHBACK_PERCENT = 0.0

# Admins
_admin_ids_env = os.getenv("ADMIN_IDS", "").replace(",", " ").split()
ADMIN_IDS = [int(x) for x in _admin_ids_env if x.isdigit()]

# Payments (defaults filled with what you gave me)
CARD_PAN  = os.getenv("CARD_PAN",  "5029081080984145")
CARD_NAME = os.getenv("CARD_NAME", "شهرزاد محمد زاده")
CARD_NOTE = os.getenv("CARD_NOTE", "لطفاً پس از کارت‌به‌کارت، رسید را در ربات ارسال کنید.")

# Instagram (===> افزوده شد)
INSTAGRAM_URL = os.getenv(
    "INSTAGRAM_URL",
    "https://www.instagram.com/bio.crepebar?igsh=MXN1cnljZTN3NGhtZw==",
).strip()

# UI
CURRENCY = "تومان"

# ---------- helpers ----------
def is_admin(tg_id: int) -> bool:
    try:
        return int(tg_id) in ADMIN_IDS
    except Exception:
        return False

def fmt_money(v) -> str:
    try:
        v = int(round(float(v)))
    except Exception:
        return f"{v} {CURRENCY}"
    s = f"{v:,}".replace(",", "،")
    return f"{s} {CURRENCY}"
