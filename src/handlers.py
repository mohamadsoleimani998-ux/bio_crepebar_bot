import os
from .base import send_message, send_photo
from .db import get_or_create_user, get_wallet, list_products, add_product

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

def _toman(cents: int) -> str:
    # هر 100 سنت = 1 تومان (برای نمایش ساده)
    return f"{cents // 100:,} تومان".replace(",", "٬")

def _parse_add_caption(caption: str):
    """
    فرمت کپشن برای افزودن محصول توسط ادمین:
    عنوان | قیمت‌به‌تومان
    مثال:  «کراپ نوتلا | 85000»
    """
    if not caption:
        return None
    parts = [p.strip() for p in caption.split("|")]
    if len(parts) != 2:
        return None
    title, price_toman = parts[0], parts[1]
    try:
        price_cents = int(price_toman) * 100
    except ValueError:
        return None
    return title, price_cents

async def _cmd_start(chat_id: int):
    await send_message(chat_id,
        "سلام! به ربات خوش آمدید.\n"
        "دستورات:\n"
        "/products — لیست محصولات\n"
        "/wallet — موجودی کیف پول"
    )

async def _cmd_wallet(chat_id: int, tg_id: int):
    user = get_or_create_user(tg_id)
    balance = _toman(user["wallet_cents"])
    await send_message(chat_id, f"موجودی کیف پول شما: {balance}")

async def _cmd_products(chat_id: int):
    items = list_products()
    if not items:
        await send_message(chat_id, "هنوز محصولی ثبت نشده است.")
        return
    lines = []
    for it in items:
        lines.append(f"• {it['title']} — { _toman(it['price_cents']) }")
    await send_message(chat_id, "\n".join(lines))

async def _handle_admin_add_by_photo(message: dict):
    """ادمین می‌تواند با ارسال عکس + کپشن «عنوان | قیمت‌به‌تومان» محصول اضافه کند."""
    chat_id = message["chat"]["id"]
    tg_id = message["from"]["id"]
    if tg_id not in ADMIN_IDS:
        return  # نادیده بگیر

    if "photo" not in message:
        return

    caption = message.get("caption", "")
    parsed = _parse_add_caption(caption)
    if not parsed:
        await send_message(chat_id, "فرمت کپشن صحیح نیست. مثال: «کراپ نوتلا | 85000»")
        return

    title, price_cents = parsed
    # بزرگ‌ترین سایز عکس را بردار
    photo_sizes = message["photo"]
    best = max(photo_sizes, key=lambda p: p.get("file_size", 0))
    file_id = best["file_id"]

    add_product(title, price_cents, file_id)
    await send_message(chat_id, f"✅ محصول «{title}» ثبت شد.")

async def handle_update(update: dict):
    # فقط Message text/photo
    if "message" not in update:
        return
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    tg_id = msg["from"]["id"]

    # اطمینان از وجود کاربر (برای کیف پول و ...)
    get_or_create_user(tg_id)

    # اگر ادمین و عکس فرستاده، تست افزودن محصول
    if "photo" in msg:
        await _handle_admin_add_by_photo(msg)
        return

    text = msg.get("text", "") or ""
    if text.startswith("/start"):
        await _cmd_start(chat_id)
    elif text.startswith("/wallet"):
        await _cmd_wallet(chat_id, tg_id)
    elif text.startswith("/products"):
        await _cmd_products(chat_id)
    else:
        # پاسخ پیش‌فرض
        await send_message(chat_id, "دستور نامعتبر است. /products یا /wallet را امتحان کنید.")
