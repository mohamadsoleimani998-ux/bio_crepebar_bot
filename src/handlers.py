from src.base import send_message  # اصلاح ایمپورت

async def handle_update(update):
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text == "/start":
            await send_message(chat_id, "سلام! به ربات خوش آمدید.")
        else:
            await send_message(chat_id, f"شما گفتید: {text}")
