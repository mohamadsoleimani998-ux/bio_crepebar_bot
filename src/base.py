import os
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def _post(method: str, payload: dict):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing")
    # httpx: fast & async-friendly (but we use sync here)
    with httpx.Client(timeout=15) as client:
        r = client.post(f"{API}/{method}", json=payload)
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
        if not data.get("ok"):
            # لاگ ساده
            print("Telegram API error:", data)
        return data

def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    return _post("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup or {"remove_keyboard": False}
    })

def send_photo(chat_id: int, photo: str, caption: str | None = None, reply_markup: dict | None = None):
    return _post("sendPhoto", {
        "chat_id": chat_id,
        "photo": photo,
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": reply_markup or {"remove_keyboard": False}
    })

def menu_keyboard() -> dict:
    # Reply Keyboard (تب منو)
    return {
        "keyboard": [
            [{"text": "/products"}, {"text": "/wallet"}],
            [{"text": "/order"}, {"text": "/help"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "is_persistent": True
    }
