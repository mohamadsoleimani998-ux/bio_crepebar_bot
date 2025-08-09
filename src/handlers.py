from base import send_message

async def handle_update(update):
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"]

        if text == "/start":
            await send_message(chat_id, "👋 سلام\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم.")
        else:
            await send_message(chat_id, text)
