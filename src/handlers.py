from typing import Dict, Any
import os

from src.base import send_message, answer_callback_query, main_menu_kb, inline_products_kb
from src.db import (
    init_db, set_admins, get_or_create_user, get_wallet,
    list_products, add_product, is_admin, place_order, add_credit
)

# حالت‌های موقتی برای دیالوگ‌های چندمرحله‌ای (در حافظه)
PENDING: dict[int, dict[str, Any]] = {}

CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "5"))

def _text_norm(s: str) -> str:
    return (s or "").strip().lower()

async def startup_warmup():
    # فقط برای اطمینان اگر جایی لازم شد
    try:
        init_db()
        admins = os.getenv("ADMIN_IDS", "")
        ids = [int(x) for x in admins.replace(" ", "").split(",") if x]
        set_admins(ids)
    except Exception as e:
        print("startup_warmup error:", e)

async def _cmd_start(chat_id: int, user: dict):
    row = get_or_create_user(user)
    admin = bool(row.get("is_admin"))
    txt = ("سلام! به ربات خوش آمدید.\n"
           "دستورات: /products , /wallet , /order\n"
           "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم.")
    await send_message(chat_id, txt, reply_markup=main_menu_kb(admin))

async def _cmd_wallet(chat_id: int, user: dict):
    bal = get_wallet(user["id"]) // 100
    await send_message(chat_id, f"موجودی کیف پول شما: {bal} تومان")

async def _cmd_products(chat_id: int, user: dict):
    items = list_products()
    if not items:
        await send_message(chat_id, "هنوز محصولی ثبت نشده است.")
        return
    # نمایش فهرست و همچنین کیبورد اینلاین برای سفارش
    lines = ["منوی امروز:"]
    for p in items:
        lines.append(f"• {p['title']} — {p['price_t']} تومان (کد {p['id']})")
    await send_message(chat_id, "\n".join(lines), reply_markup=inline_products_kb(items))

async def _cmd_order(chat_id: int, user: dict):
    items = list_products()
    if not items:
        await send_message(chat_id, "فعلاً منویی وجود ندارد.")
        return
    await send_message(chat_id, "برای ثبت سفارش یکی از موارد زیر را انتخاب کنید:", reply_markup=inline_products_kb(items))

async def _cmd_addproduct_start(chat_id: int, user: dict):
    if not is_admin(user["id"]):
        await send_message(chat_id, "دسترسی ادمین ندارید.")
        return
    PENDING[user["id"]] = {"state": "await_title"}
    await send_message(chat_id, "عنوان محصول را بفرستید:")

async def _handle_pending(chat_id: int, user: dict, text: str) -> bool:
    st = PENDING.get(user["id"])
    if not st:
        return False
    if st["state"] == "await_title":
        st["title"] = text.strip()
        st["state"] = "await_price"
        await send_message(chat_id, "قیمت را به تومان بفرستید (مثلاً 85000):")
        return True
    if st["state"] == "await_price":
        try:
            price_t = int(text.strip())
        except ValueError:
            await send_message(chat_id, "عدد معتبر نیست. دوباره قیمت را به تومان بفرستید.")
            return True
        add_product(st["title"], price_t)
        PENDING.pop(user["id"], None)
        await send_message(chat_id, f"محصول «{st['title']}» با قیمت {price_t} تومان اضافه شد.")
        await _cmd_products(chat_id, user)
        return True
    return False

async def _handle_callback(cb: dict):
    data = cb.get("data") or ""
    cb_id = cb.get("id")
    msg = cb.get("message") or {}
    chat = (msg.get("chat") or {})
    chat_id = chat.get("id")
    from_user = cb.get("from") or {}
    if data.startswith("order:"):
        try:
            pid = int(data.split(":", 1)[1])
        except Exception:
            await answer_callback_query(cb_id, "داده نامعتبر است.")
            return
        ok, info = place_order(from_user["id"], pid, 1, CASHBACK_PERCENT)
        await answer_callback_query(cb_id, "ثبت شد" if ok else "خطا")
        await send_message(chat_id, info)

async def handle_update(update: Dict[str, Any]):
    try:
        if "callback_query" in update:
            await _handle_callback(update["callback_query"])
            return

        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = msg.get("text") or ""
        from_user = msg.get("from") or {}

        # اگر کار در حالت معلق (افزودن محصول) بود
        if await _handle_pending(chat_id, from_user, text):
            return

        t = _text_norm(text)
        # پشتیبانی از دکمه‌های فارسی بدون اسلش
        if t in ("/start", "start"):
            await _cmd_start(chat_id, from_user)
        elif t in ("/wallet", "wallet", "💼 کیف پول", "کیف پول"):
            await _cmd_wallet(chat_id, from_user)
        elif t in ("/products", "products", "🍽 منو", "منو", "/menu", "menu"):
            await _cmd_products(chat_id, from_user)
        elif t in ("/order", "order", "🛒 ثبت سفارش", "ثبت سفارش"):
            await _cmd_order(chat_id, from_user)
        elif t in ("/addproduct", "addproduct", "➕ افزودن محصول", "افزودن محصول"):
            await _cmd_addproduct_start(chat_id, from_user)
        else:
            # دکمه «منو» همیشه برگردانده شود
            await _cmd_start(chat_id, from_user)
    except Exception as e:
        print("handle_update error:", e)
        try:
            chat_id = ((update.get("message") or {}).get("chat") or {}).get("id")
            if chat_id:
                await send_message(chat_id, "مشکلی رخ داد. لطفاً دوباره تلاش کنید.")
        except:
            pass
