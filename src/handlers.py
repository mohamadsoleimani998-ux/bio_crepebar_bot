# ایمپورت نسبی داخل پکیج src
from .base import send_message
# اگر بعداً دیتابیس خواستی، این‌ها رو فعال می‌کنیم:
# from .db import get_or_create_user, add_balance, get_balance, is_admin, add_product

async def handle_update(update: dict):
    # فقط پیام متنی را پردازش می‌کنیم تا خطا ندهد
    if "message" not in update or "text" not in update["message"]:
        return

    chat_id = update["message"]["chat"]["id"]
    text = update["message"]["text"].strip()

    if text == "/start":
        await send_message(chat_id, "سلام! به ربات خوش آمدید.")
    else:
        # فعلاً اکو تا اطمینان از پایداری
        await send_message(chat_id, text)
