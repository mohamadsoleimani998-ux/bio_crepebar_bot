from base import send_message
from db import (
    init_db,           # فقط در استارتاپ استفاده می‌شود
    set_admins,        # اگر جایی لازم شد ادمین‌ها ست شوند
    get_or_create_user,
    get_wallet,
    list_products,
    add_product,
)

# ————— ابزارهای کمکی —————
def _keyboard(is_admin: bool):
    rows = [[{"text": "/products"}, {"text": "/wallet"}]]
    if is_admin:
        rows.append([{"text": "/addproduct"}])
    return {"keyboard": rows, "resize_keyboard": True}

def _parse_addproduct_args(s: str):
    """
    ورودی بعد از /addproduct را می‌گیرد و (title, price_toman) برمی‌گرداند.
    فرمت‌های قابل قبول:
      /addproduct عنوان | 35000
      /addproduct عنوان 35000
    """
    s = (s or "").strip()
    if not s:
        return None, None

    if "|" in s:
        left, right = s.split("|", 1)
        title = left.strip()
        price_txt = right.strip()
    else:
        parts = s.split()
        if len(parts) < 2:
            return None, None
        # قیمت آخرین بخش است، بقیه عنوان
        price_txt = parts[-1]
        title = " ".join(parts[:-1]).strip()

    try:
        price_toman = int(price_txt.replace(",", ""))
    except Exception:
        return None, None

    if not title:
        return None, None
    return title, price_toman

# ————— هندل اصلی آپدیت —————
async def handle_update(update: dict):
    """
    همین تابع قبلی که کار می‌کرد، فقط شاخه‌ی /addproduct و کیبورد اضافه شده.
    """
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        from_user = msg.get("from") or {}
        tg_id = from_user.get("id")
        text = (msg.get("text") or "").strip()

        # کاربر را ایجاد/واکشی کن
        user = get_or_create_user(tg_id)
        is_admin = bool(user.get("is_admin"))

        # کیبورد (تب‌ها) برای همه پیام‌ها
        kb = _keyboard(is_admin)

        # /start
        if text.startswith("/start"):
            hello = (
                "سلام! به ربات خوش آمدید.\n"
                "دستورات: /products , /wallet/\n"
                "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم."
            )
            await send_message(chat_id, hello, reply_markup=kb)
            return

        # /wallet
        if text.startswith("/wallet"):
            wallet_cents = get_wallet(tg_id)
            # فرض: واحد تومان است (هر 10 ریال = 1 تومان). اگر در db تومان ذخیره می‌کنید همین را عوض نکنید.
            tomans = wallet_cents // 10
            await send_message(chat_id, f"موجودی کیف پول شما: {tomans} تومان", reply_markup=kb)
            return

        # /products
        if text.startswith("/products"):
            items = list_products()
            if not items:
                await send_message(chat_id, "هنوز محصولی ثبت نشده است.", reply_markup=kb)
                return

            lines = []
            for p in items:
                # p: {id,title,price_cents,...}
                price_toman = int(p.get("price_cents", 0)) // 10
                lines.append(f"• {p.get('title','')} — {price_toman} تومان")
            await send_message(chat_id, "\n".join(lines), reply_markup=kb)
            return

        # /addproduct  (فقط ادمین)
        if text.startswith("/addproduct"):
            if not is_admin:
                await send_message(chat_id, "دسترسی لازم ندارید.", reply_markup=kb)
                return

            args = text[len("/addproduct"):].strip()
            title, price_toman = _parse_addproduct_args(args)
            if not title or price_toman is None:
                usage = (
                    "فرمت درست:\n"
                    "/addproduct عنوان | قیمت_تومان\n"
                    "یا:\n"
                    "/addproduct عنوان قیمت_تومان\n"
                    "مثال: /addproduct کرپ موزی | 85000"
                )
                await send_message(chat_id, usage, reply_markup=kb)
                return

            # تبدیل تومان به سنت/ریال ذخیره‌شده در DB (اینجا مثل بقیه جاها ×10)
            price_cents = int(price_toman) * 10

            # اگر بعدا عکس و کپشن لازم شد، می‌توانیم از msg.photo و msg.caption استفاده کنیم.
            add_product(title=title, price_cents=price_cents, photo_file_id=None, caption=None)

            await send_message(chat_id, f"✅ محصول «{title}» با قیمت {price_toman} تومان اضافه شد.", reply_markup=kb)
            return

        # سایر پیام‌ها: فقط کیبورد را نگه داریم
        await send_message(chat_id, "دستور نامعتبر است.", reply_markup=kb)

    except Exception as e:
        # لاگ خطا؛ سرویس لایو بماند
        print("handle_update error:", e)


# ————— استارت‌آپ (برای گرم‌کردن و اطمینان از اسکیمای DB) —————
def startup_warmup():
    try:
        init_db()
    except Exception as e:
        print("init_db error:", e)
