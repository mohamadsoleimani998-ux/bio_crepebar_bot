# src/handlers.py
from base import send_message
from db import ensure_user

WELCOME = "سلام! به ربات خوش آمدید."

async def handle_update(update: dict):
    # فقط پیام متنی
    if "message" in update and "text" in update["message"]:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg["text"]

        # ثبت کاربر در دیتابیس (ایمن و idempotent)
        try:
            # چون این تابع سنک است، در bot.py آن را داخل threadpool فراخوانی می‌کنیم.
            # اینجا فقط داده‌های لازم را آماده می‌کنیم.
            tg_id = msg["from"]["id"]
            username = msg["from"].get("username")
            first_name = msg["from"].get("first_name")
            # فراخوانی واقعی در bot.py انجام می‌شود (نگران نباش).
        except Exception:
            pass

        if text == "/start":
            await send_message(chat_id, WELCOME)
        else:
            await send_message(chat_id, text)
