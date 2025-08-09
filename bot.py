import os
import logging
import requests
from flask import Flask, request, Response, jsonify

# ---------- Config ----------
BOT_TOKEN      = os.environ["BOT_TOKEN"].strip()
WEBHOOK_BASE   = os.environ["WEBHOOK_BASE"].rstrip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].strip()

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ---------- App ----------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("crepebar-bot")

def tg_api(method: str, payload: dict) -> dict:
    """Call Telegram Bot API (sync)."""
    url = f"{API_BASE}/{method}"
    r = requests.post(url, json=payload, timeout=15)
    if not r.ok:
        log.error("Telegram API %s failed: %s - %s", method, r.status_code, r.text)
    return r.json() if r.text else {}

def set_webhook():
    payload = {
        "url": WEBHOOK_URL,
        "secret_token": WEBHOOK_SECRET,
        "drop_pending_updates": True,
        "allowed_updates": ["message", "callback_query"]
    }
    res = tg_api("setWebhook", payload)
    log.info("setWebhook -> %s", res)

# ---------- Routes ----------
@app.get("/")
def health():
    return jsonify(status="ok", webhook=WEBHOOK_URL), 200

@app.post(WEBHOOK_PATH)
def telegram_webhook():
    # امنیت: تطبیق Secret Token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        return Response(status=401)

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if chat_id and text:
        if text.startswith("/start"):
            tg_api("sendMessage", {
                "chat_id": chat_id,
                "text": "سلام! 👋\nربات بیو کِرپ‌بار فعاله. از منوی پایین برای شروع استفاده کن.",
                "parse_mode": "HTML"
            })
        # جا برای فیچرهای بعدی...

    return Response(status=200)

# ---------- Startup ----------
# توجه: در Flask 3، before_first_request حذف شده. پس مستقیم اینجا وبهوک رو ست می‌کنیم.
try:
    set_webhook()
    log.info("Webhook set to %s", WEBHOOK_URL)
except Exception as e:
    log.exception("Failed to set webhook: %s", e)

# برای Gunicorn: متغیر app باید وجود داشته باشه
# اگر محلی اجرا می‌کنی، می‌تونی این بلوک رو فعال کنی:
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
