from base import send_message

async def handle_update(update: dict):
    # فقط پیام‌های متنی را پاسخ بده
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"]

        if text == "/start":
            await send_message(chat_id, "سلام! ربات فعاله ✅\nهر متنی بفرست تا همونو برگردونم.")
        else:
            await send_message(chat_id, text)
