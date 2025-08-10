from src.base import send_message, send_photo, menu_keyboard
from src.db import (
    init_db, get_or_create_user, get_wallet, list_products, add_product,
    create_order, add_item_to_order, apply_cashback, is_admin, set_admins
)

WELCOME = (
    "سلام! به ربات خوش آمدید.\n"
    "دستورات: /products , /wallet , /order , /help\n"
    "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم."
)

def _get_msg(update: dict) -> dict | None:
    # message یا edited_message یا callback
    return update.get("message") or update.get("edited_message") or {}

def _user_from(update: dict) -> dict | None:
    msg = _get_msg(update)
    return msg.get("from")

def _chat_id(update: dict) -> int | None:
    msg = _get_msg(update)
    chat = msg.get("chat") or {}
    return chat.get("id")

def _text(update: dict) -> str:
    msg = _get_msg(update)
    return (msg.get("text") or "").strip()

def startup_warmup():
    # جایی برای کارهای استارتاپ (لاگ ساده)
    print("startup warmup done")

# -------------- Commands --------------
def _cmd_start(chat_id: int, tg_user: dict):
    get_or_create_user(tg_user)  # تضمین ثبت
    send_message(chat_id, WELCOME, reply_markup=menu_keyboard())

def _cmd_wallet(chat_id: int, tg_user: dict):
    me = get_or_create_user(tg_user)
    cents = get_wallet(me["user_id"])
    send_message(chat_id, f"موجودی کیف پول شما: {cents//10} تومان")

def _cmd_products(chat_id: int):
    items = list_products()
    if not items:
        send_message(chat_id, "هنوز محصولی ثبت نشده است.")
        return
    lines = []
    for p in items:
        price_toman = p["price_cents"] // 10
        lines.append(f"{p['id']}) {p['name']} — {price_toman} تومان")
    send_message(chat_id, "منو:\n" + "\n".join(lines))

def _cmd_order(chat_id: int, tg_user: dict):
    user = get_or_create_user(tg_user)
    # برای نمونه: یک سفارش درفت بدون آیتم
    order_id = create_order(user["user_id"])
    send_message(chat_id, f"سفارش #{order_id} ایجاد شد. برای افزودن آیتم: /add <product_id> <qty>")

def _cmd_add(chat_id: int, tg_user: dict, args: list[str]):
    user = get_or_create_user(tg_user)
    if len(args) < 1:
        send_message(chat_id, "فرمت: /add <product_id> [qty]")
        return
    try:
        pid = int(args[0])
        qty = int(args[1]) if len(args) > 1 else 1
    except ValueError:
        send_message(chat_id, "شناسه/تعداد نامعتبر است.")
        return
    # سفارش جدید می‌سازیم و آیتم اضافه می‌کنیم (نسخه ساده)
    order_id = create_order(user["user_id"])
    add_item_to_order(order_id, pid, qty)
    # فرض کنیم مبلغ سفارش را گرفتیم؛ کش‌بک:
    # (در عمل باید total را بخوانیم؛ اینجا ساده‌سازی می‌کنیم)
    send_message(chat_id, f"آیتم به سفارش #{order_id} اضافه شد.")
    # کش‌بک نمونه: 5% روی 1 قلم با خواندن قیمت واقعی—برای سادگی رد می‌کنیم.

def _cmd_admin_add(chat_id: int, tg_user: dict, args: list[str]):
    if not is_admin(tg_user["id"]):
        send_message(chat_id, "اجازه دسترسی ندارید.")
        return
    if len(args) < 2:
        send_message(chat_id, "فرمت: /admin_add <name> <price_toman> [photo_url]")
        return
    name = args[0]
    try:
        toman = int(args[1])
    except ValueError:
        send_message(chat_id, "قیمت نامعتبر است.")
        return
    price_cents = toman * 10
    photo_url = args[2] if len(args) > 2 else None
    pid = add_product(name, price_cents, photo_url)
    send_message(chat_id, f"محصول جدید ثبت شد (ID={pid}).")

def _cmd_set_admins(chat_id: int, tg_user: dict, args: list[str]):
    if not is_admin(tg_user["id"]):
        send_message(chat_id, "اجازه دسترسی ندارید.")
        return
    ids = []
    for a in args:
        try:
            ids.append(int(a))
        except ValueError:
            pass
    set_admins(ids)
    send_message(chat_id, f"ادمین‌ها به‌روزرسانی شد: {ids}")

# -------------- Router --------------
async def handle_update(update: dict):
    try:
        chat_id = _chat_id(update)
        tg_user = _user_from(update)
        if not chat_id or not tg_user:
            # چیزی برای پاسخ نیست
            return

        text = _text(update)
        if not text.startswith("/"):
            # ورودی آزاد (در آینده: پشتیبانی از فرم‌ها)
            send_message(chat_id, "برای شروع از منو یا دستورات استفاده کنید.", reply_markup=menu_keyboard())
            return

        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "/start":
            _cmd_start(chat_id, tg_user)
        elif cmd == "/wallet":
            _cmd_wallet(chat_id, tg_user)
        elif cmd == "/products":
            _cmd_products(chat_id)
        elif cmd == "/order":
            _cmd_order(chat_id, tg_user)
        elif cmd == "/add":
            _cmd_add(chat_id, tg_user, args)
        elif cmd == "/admin_add":
            _cmd_admin_add(chat_id, tg_user, args)
        elif cmd == "/set_admins":
            _cmd_set_admins(chat_id, tg_user, args)
        elif cmd == "/help":
            send_message(chat_id, "راهنما:\n/products نمایش منو\n/wallet کیف پول\n/order ثبت سفارش ساده", reply_markup=menu_keyboard())
        else:
            send_message(chat_id, "دستور ناشناخته.", reply_markup=menu_keyboard())

    except Exception as e:
        # لاگ خطا؛ ولی سرویس لایو می‌ماند
        print("handle_update error:", e)
