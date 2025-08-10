from .base import send_message, send_photo, ADMIN_IDS, CASHBACK_PERCENT
from .db import (
    init_db, set_admins, get_or_create_user, get_wallet,
    list_products, add_product
)

WELCOME = (
    "سلام! به ربات خوش آمدید.\n"
    "دستورات: /products , /wallet/\n"
    "اگر ادمین هستید، برای افزودن یک محصول با عکس، "
    "عکسِ محصول را با کپشن به فرمِ «نام محصول | قیمت به تومان» بفرستید."
)

def _ensure_user(update):
    msg = update.get("message") or update.get("edited_message") or {}
    frm = msg.get("from", {})
    tg_id = int(frm.get("id", 0))
    if tg_id:
        get_or_create_user(tg_id)
    return tg_id

async def handle_update(update: dict):
    try:
        tg_id = _ensure_user(update)
        # ادمین‌ها را یک‌بار همگام کن (بی‌ضرر است)
        set_admins(ADMIN_IDS)

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat_id = int(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()

        # فرمان‌ها
        if text.startswith("/start"):
            send_message(chat_id, WELCOME)
            return

        if text.startswith("/wallet"):
            balance = get_wallet(tg_id)
            send_message(chat_id, f"موجودی کیف پول شما: {balance//100:,} تومان")
            return

        if text.startswith("/products"):
            items = list_products()
            if not items:
                send_message(chat_id, "هنوز محصولی ثبت نشده است.")
                return
            out = ["لیست محصولات:"]
            for p in items:
                out.append(f"• {p['name']} - {p['price_cents']//100:,} تومان")
            send_message(chat_id, "\n".join(out))
            return

        # افزودن محصول توسط ادمین با ارسال عکس + کپشن "نام | قیمت"
        if msg.get("photo") and tg_id in ADMIN_IDS:
            caption = (msg.get("caption") or "").strip()
            if "|" not in caption:
                send_message(chat_id, "فرمت کپشن صحیح نیست. مثال: «کراپ ویژه | ۱۲۰۰۰۰»")
                return
            name, price_txt = [x.strip() for x in caption.split("|", 1)]
            # تبدیل تومان به سنت (ریال/۱۰۰) برای سادگی: هر ۱ تومان = ۱۰۰ سنت
            # (اگر فقط تومان می‌خواهی ذخیره کنی، می‌توانی *100 را حذف کنی)
            price_num = 0
            try:
                price_num = int(price_txt.replace(",", "").replace("تومان", "").replace(" ", ""))
            except Exception:
                send_message(chat_id, "قیمت عددی نیست.")
                return
            price_cents = price_num * 100

            photo_sizes = msg.get("photo") or []
            file_id = photo_sizes[-1]["file_id"] if photo_sizes else None
            add_product(name, price_cents, file_id)
            send_message(chat_id, "محصول با موفقیت افزوده شد ✅")
            if file_id:
                send_photo(chat_id, file_id, f"{name} - {price_num:,} تومان")
            return

        # ناشناخته
        if text:
            send_message(chat_id, "دستور ناشناخته است. /start را بزنید.")
    except Exception as e:
        # هر اروری رخ دهد، سرویس لایو می‌ماند و فقط لاگ می‌گیریم
        print("handle_update error:", e)
