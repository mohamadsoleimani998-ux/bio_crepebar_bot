from .base import send_message

async def handle_update(update: dict):
    # فقط پیام‌های متنی
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        await send_message(chat_id, "سلام! به ربات خوش آمدید.")
    elif text:
        await send_message(chat_id, f"دریافت شد: {text}")
