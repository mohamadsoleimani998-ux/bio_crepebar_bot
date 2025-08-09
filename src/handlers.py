from base import send_message

START_TEXT = "👋 سلام\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."

async def handle_update(update: dict):
    # فقط پیام‌های متنی را جواب بده
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"].strip()

        if text == "/start":
            await send_message(chat_id, START_TEXT)
        else:
            await send_message(chat_id, text)
