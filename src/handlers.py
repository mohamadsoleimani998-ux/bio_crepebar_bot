# ایمپورت اصلاح‌شده
from .base import send_message

def handle_update(update):
    message = update.get("message", {}).get("text", "")
    chat_id = update.get("message", {}).get("chat", {}).get("id", "")

    if message == "/start":
        send_message(chat_id, "سلام! ربات فعال است 😊")
    else:
        send_message(chat_id, f"پیام دریافت شد: {message}")
