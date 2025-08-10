from .base import send_message  # ایمپورت نسبی از داخل پکیج src

async def handle_update(update: dict):
    # فقط اگر Message متنی باشد
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text    = update["message"]["text"]

        if text == "/start":
            await send_message(chat_id, "سلام! به ربات خوش آمدید.")
        else:
            await send_message(chat_id, "دریافت شد.")
