import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# ادمین‌ها: مثلا "123,456"
_admins_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admins_raw.replace(" ", "").split(",") if x.isdigit()}

CASHBACK_PERCENT = 0
try:
    CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "0"))
except Exception:
    CASHBACK_PERCENT = 0

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(chat_id: int, text: str, reply_to_message_id: int | None = None):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        r = requests.post(f"{API_BASE}/sendMessage", json=data, timeout=10)
        if not r.ok:
            print("send_message error:", r.text)
    except Exception as e:
        print("send_message exception:", e)

def send_photo(chat_id: int, file_id: str, caption: str | None = None):
    try:
        data = {"chat_id": chat_id, "photo": file_id}
        if caption:
            data["caption"] = caption
        r = requests.post(f"{API_BASE}/sendPhoto", json=data, timeout=15)
        if not r.ok:
            print("send_photo error:", r.text)
    except Exception as e:
        print("send_photo exception:", e)
