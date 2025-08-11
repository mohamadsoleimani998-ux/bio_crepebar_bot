from __future__ import annotations
from typing import Final, Dict, Any
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from .base import SETTINGS
from . import db

# ===== Keyboards ==============================================================
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["/products", "/wallet"],
        ["/order", "/help"],
        ["/contact", "/game"]
    ],
    resize_keyboard=True
)

# ===== Helpers ================================================================
def is_admin(user_id: int) -> bool:
    return user_id in SETTINGS.ADMIN_IDS

# ===== /start /help ===========================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.username, u.full_name)
    text = (
        "سلام! به ربات خوش آمدید.\n"
        "دستورات: /products , /wallet , /order , /help , /contact , /game\n"
        "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم."
    )
    await update.message.reply_text(text, reply_markup=MAIN_KB)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنما:\n"
        "/products نمایش منو\n"
        "/wallet کیف پول\n"
        "/order ثبت سفارش ساده\n"
        "/contact ارتباط با ما\n"
        "/game بازی فان 🎲",
        reply_markup=MAIN_KB
    )

# ===== Products ==============================================================

async def cmd_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products(active_only=True)
    if not prods:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.", reply_markup=MAIN_KB)
        return
    for p in prods:
        cap = f"{p['title']} — {p['price']} تومان"
        if p.get("photo_id"):
            try:
                await update.message.reply_photo(p["photo_id"], caption=cap)
            except Exception:
                await update.message.reply_text(cap)
        else:
            await update.message.reply_text(cap)

# ----- Admin: add product (conversation) -------------------------------------
AP_TITLE, AP_PRICE, AP_PHOTO = range(3)

async def cmd_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("دسترسی ندارید.")
    await update.message.reply_text("عنوان محصول را بفرستید:")
    return AP_TITLE

async def ap_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ap_title"] = (update.message.text or "").strip()
    await update.message.reply_text("قیمت (تومان) را بفرستید:")
    return AP_PRICE

async def ap_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int((update.message.text or "0").replace(",", "").strip())
    except ValueError:
        return await update.message.reply_text("عدد صحیح بفرستید.")
    context.user_data["ap_price"] = price
    await update.message.reply_text("عکس محصول را ارسال کنید (یا /skip):")
    return AP_PHOTO

async def ap_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    t = context.user_data.pop("ap_title")
    p = context.user_data.pop("ap_price")
    pid = db.add_product(t, p, photo_id)
    await update.message.reply_text(f"محصول ثبت شد (ID={pid}).", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def ap_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = context.user_data.pop("ap_title")
    p = context.user_data.pop("ap_price")
    pid = db.add_product(t, p, None)
    await update.message.reply_text(f"محصول بدون عکس ثبت شد (ID={pid}).", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== Order (conversation: جمع‌آوری اطلاعات مشتری + آیتم‌ها) ===============
O_NAME, O_PHONE, O_ADDRESS, O_ITEMS = range(4)

async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("نام و نام‌خانوادگی را بفرستید:")
    return O_NAME

async def o_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["o_name"] = update.message.text.strip()
    await update.message.reply_text("شماره تماس را بفرستید:")
    return O_PHONE

async def o_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["o_phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس کامل را بفرستید:")
    return O_ADDRESS

async def o_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["o_address"] = update.message.text.strip()
    prods = db.list_products(active_only=True)
    if not prods:
        await update.message.reply_text("هنوز محصولی نداریم. بعداً امتحان کنید.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    lines = ["شناسه و تعداد را با قالب زیر بفرستید:", "مثال:  12x2, 5x1"]
    ids = []
    for p in prods:
        lines.append(f"#{p['id']} — {p['title']} ({p['price']} ت)")
        ids.append(p["id"])
    context.user_data["o_product_map"] = {p["id"]: p for p in prods}
    await update.message.reply_text("\n".join(lines))
    return O_ITEMS

def _parse_items(text: str) -> list[tuple[int, int]]:
    res = []
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        if "x" not in chunk:
            return []
        a, b = chunk.split("x", 1)
        if not (a.isdigit() and b.isdigit()):
            return []
        res.append((int(a), int(b)))
    return res

async def o_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = _parse_items(update.message.text or "")
    if not pairs:
        return await update.message.reply_text("قالب نامعتبر. مثل «12x2, 5x1» بفرستید.")
    pmap: Dict[int, Dict[str, Any]] = context.user_data["o_product_map"]
    items = []
    for pid, qty in pairs:
        if pid not in pmap:
            return await update.message.reply_text(f"شناسه {pid} یافت نشد.")
        p = pmap[pid]
        items.append({"product_id": pid, "title": p["title"], "qty": qty, "unit_price": p["price"]})
    uid = update.effective_user.id
    name = context.user_data["o_name"]
    phone = context.user_data["o_phone"]
    address = context.user_data["o_address"]
    db.update_profile(uid, phone, address, name)
    order_id = db.create_order(uid, name, phone, address, items, SETTINGS.CASHBACK_PERCENT)
    order = db.get_order(order_id)
    lines = [f"سفارش #{order_id} ثبت شد ✅", "آیتم‌ها:"]
    for it in order["items"]:
        lines.append(f"- {it['title']} ×{it['qty']} — {it['unit_price']} ت")
    lines.append(f"جمع: {order['subtotal']} ت")
    if order["cashback"]:
        lines.append(f"کش‌بک: {order['cashback']} ت ✅ (به کیف پولتان اضافه شد)")
    lines.append(f"مبلغ پرداختی: {order['total']} ت")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_KB)
    for admin_id in SETTINGS.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"سفارش جدید #{order_id}\n"
                f"مشتری: {name}\n"
                f"تلفن: {phone}\n"
                f"آدرس: {address}\n"
                f"جمع: {order['subtotal']} | پرداختی: {order['total']}"
            )
        except Exception:
            pass
    return ConversationHandler.END

# ===== Wallet ================================================================

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = db.get_wallet(uid)
    await update.message.reply_text(f"موجودی کیف پول شما: {bal} تومان", reply_markup=MAIN_KB)
    if bal == 0:
        await update.message.reply_text(
            "برای شارژ کارت‌به‌کارت، رسید را اینجا بفرستید و "
            "ادمین پس از بررسی شارژ می‌کند. (به‌زودی درگاه پرداخت اضافه می‌شود.)"
        )

async def cmd_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("دسترسی ندارید.")
    if len(context.args) != 2 or not all(x.isdigit() for x in context.args):
        return await update.message.reply_text("قالب: /charge <user_id> <amount>")
    user_id, amount = map(int, context.args)
    db.add_wallet_tx(user_id, amount, "manual", {"by": update.effective_user.id})
    await update.message.reply_text("انجام شد ✅")

# ===== Contact ===============================================================
C_MSG = 1

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را بفرستید تا برای ادمین ارسال شود:")
    return C_MSG

async def c_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text or ""
    uid = update.effective_user.id
    for admin_id in SETTINGS.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"پیام کاربر {uid}:\n{txt}")
        except Exception:
            pass
    await update.message.reply_text("ارسال شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== Game ==================================================================
async def cmd_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_dice(emoji="🎯")

# ===== Registrar =============================================================
def register(application: Application):
    # به‌جای JobQueue، همین‌جا DB را initialize می‌کنیم تا خطای None برطرف شود.
    db.init_db()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("products", cmd_products))
    application.add_handler(CommandHandler("wallet", cmd_wallet))
    application.add_handler(CommandHandler("game", cmd_game))
    application.add_handler(CommandHandler("charge", cmd_charge))

    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addproduct", cmd_add_product)],
        states={
            AP_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_title)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [
                MessageHandler(filters.PHOTO, ap_photo),
                CommandHandler("skip", ap_skip),
            ],
        },
        fallbacks=[CommandHandler("cancel", ap_skip)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("order", cmd_order)],
        states={
            O_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_name)],
            O_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_phone)],
            O_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_address)],
            O_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_items)],
        },
        fallbacks=[CommandHandler("cancel", cmd_start)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("contact", cmd_contact)],
        states={C_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, c_msg)]},
        fallbacks=[CommandHandler("cancel", cmd_start)],
    ))
