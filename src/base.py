# src/base.py
import os
import logging

# --- ENV ---
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("WEBHOOK_BASE") or "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_FULL") or ""

# --- logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")
