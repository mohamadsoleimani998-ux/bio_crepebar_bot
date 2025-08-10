import os
from typing import Any, Dict

from src.base import send_message, send_menu, set_my_commands
from src.db import get_or_create_user, get_wallet, list_products
# اختیاری‌ها: اگر پیاده‌سازی نشده باشند، ایمپورت بی‌اثر می‌شود
try:
    from src.db import add_product, set_admins  # type: ignore
except Exception:
    add_product = None
    set_admins = None

BOT_USERNAME = os.getenv("BOT_USERNAME")  # اختیاری

def _get_update_parts(update: Dict[str, Any]):
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    from_user = msg.get("from") or {}
    return chat_id, text, from_user

async def _handle_command(chat_id: int, cmd: str, from_user: Dict[str, Any]):
    # کاربر را بساز/بروزرسانی کن (جلوگیری از خطای نال)
    try:
        get_or_create_user(
            tg_id=from_user.get("id"),
            first_name=from_user.get("first_name"),
            last_name=from_user.get("last_name"),
            username=from_user.get("username"),
        )
    except Exception as e:
        print("get_or_create_user error:", e)

    if cmd in ("/start", f"/start@{BOT_USERNAME}" if BOT_USERNAME else ""):
        set_my_commands([
            ("start", "شروع"),
            ("products", "مشاهده محصولات"),
            ("wallet", "کیف پول"),
        ])
        await send_menu(chat_id)
        return

    if cmd.startswith("/wallet"):
        try:
            cents = get_wallet(from_user.get("id"))
            tomans = cents // 10  # در صورت نیاز تغییر بده
            await send_message(chat_id, f"موجودی کیف پول شما: {tomans} تومان")
        except Exception as e:
            print("wallet error:", e)
            await send_message(chat_id, "خطا در دریافت کیف پول.")
        return

    if cmd.startswith("/products"):
        try:
            items = list_products()
            if not items:
                await send_message(chat_id, "هنوز محصولی ثبت نشده است.")
            else:
                lines = []
                for it in items:
                    price_t = (it.get("price_cents") or 0) // 10
                    lines.append(f"• {it.get('title')} — {price_t} تومان")
                await send_message(chat_id, "\n".join(lines))
        except Exception as e:
            print("products error:", e)
            await send_message(chat_id, "خطا در نمایش محصولات.")
        return

    await send_message(chat_id, "دستور ناشناخته است. /start را بفرستید.")

async def handle_update(update: Dict[str, Any]):
    try:
        chat_id, text, from_user = _get_update_parts(update)
        if not chat_id:
            return
        if text.startswith("/"):
            await _handle_command(chat_id, text.split()[0], from_user)
        else:
            await send_message(chat_id, "برای راهنما: /start")
    except Exception as e:
        print("handle_update error:", e)

async def startup_warmup():
    # فقط ثبت دستورات در استارتاپ
    set_my_commands([
        ("start", "شروع"),
        ("products", "مشاهده محصولات"),
        ("wallet", "کیف پول"),
    ])
