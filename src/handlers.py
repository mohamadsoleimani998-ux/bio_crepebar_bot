from typing import Dict, Tuple, List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters, CallbackQueryHandler
)
from . import db
from .base import HELP_TEXT, CONTACT_TEXT, GAME_TEXT, is_admin, CASHBACK_PERCENT

# ---- Start / Help / Menu
def main_menu_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("/products"), KeyboardButton("/wallet")],
         [KeyboardButton("/order"), KeyboardButton("/help")]],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_user(u.id, u.first_name or "", u.last_name or "")
    await update.message.reply_text(
        "سلام! به ربات خوش آمدید.\nدستورات: /help , /order , /wallet , /products , /contact\n"
        "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم.",
        reply_markup=main_menu_kb()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(CONTACT_TEXT)

async def echo_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # هر پیامی بعد از /contact بیاید، برای ادمین فوروارد می‌کنیم
    if not context.user_data.get("await_contact"):
        return
    admins = context.bot_data.get("ADMINS", [])
    for aid in admins:
        try:
            await context.bot.forward_message(chat_id=aid, from_chat_id=update.effective_chat.id,
                                              message_id=update.message.message_id)
        except Exception:
            pass
    context.user_data["await_contact"] = False
    await update.message.reply_text("پیام شما برای ادمین ارسال شد ✅")

async def contact_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["await_contact"] = True
    await contact_cmd(update, context)

# ---- Products
async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.list_products()
    if not items:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    lines = []
    kb_rows = []
    for p in items:
        lines.append(f"#{p['id']} - {p['name']} — {p['price']} تومان")
        kb_rows.append([InlineKeyboardButton(f"سفارش #{p['id']}", callback_data=f"order:{p['id']}")])
    text = "منو:\n" + "\n".join(lines)
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))

# ---- Order conversation
ORDER_PICK, ORDER_QTY, ORDER_NAME, ORDER_PHONE, ORDER_ADDRESS, ORDER_CONFIRM = range(6)

async def order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.list_products()
    if not items:
        await update.message.reply_text("منو خالی است. ابتدا محصول اضافه کنید.")
        return ConversationHandler.END
    lines = [f"برای شروع، شناسه محصول را بفرستید (مثلاً 1):"]
    for p in items:
        lines.append(f"#{p['id']} - {p['name']} — {p['price']} تومان")
    await update.message.reply_text("\n".join(lines))
    return ORDER_PICK

async def order_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip().lstrip("#"))
    except Exception:
        await update.message.replyText("شناسه نامعتبر است. دوباره ارسال کنید.")
        return ORDER_PICK
    prod = db.get_product(pid)
    if not prod:
        await update.message.reply_text("محصول یافت نشد. شناسه دیگری بفرستید.")
        return ORDER_PICK
    context.user_data["order_pid"] = pid
    await update.message.reply_text(f"تعداد {prod['name']}؟ (عدد ارسال کنید)")
    return ORDER_QTY

async def order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("تعداد نامعتبر است. یک عدد مثبت بفرستید.")
        return ORDER_QTY
    context.user_data["order_qty"] = qty
    await update.message.reply_text("نام و نام خانوادگی:")
    return ORDER_NAME

async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_name"] = update.message.text.strip()
    await update.message.reply_text("شماره تماس:")
    return ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس کامل:")
    return ORDER_ADDRESS

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_address"] = update.message.text.strip()
    pid = context.user_data["order_pid"]
    qty = context.user_data["order_qty"]
    prod = db.get_product(pid)
    total = prod["price"] * qty
    await update.message.reply_text(
        f"تأیید سفارش:\n"
        f"{prod['name']} × {qty}\n"
        f"مبلغ کل: {total} تومان\n"
        f"با ارسال «تأیید» ثبت می‌شود."
    )
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() not in ("تایید", "تأیید", "تایيد", "تایید"):
        await update.message.reply_text("لغو شد.")
        return ConversationHandler.END

    user = update.effective_user
    pid = context.user_data["order_pid"]
    qty = context.user_data["order_qty"]
    full_name = context.user_data["order_name"]
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]

    db.upsert_user_contact(user.id, full_name, phone, address)
    order_id = db.create_order(
        user_id=user.id,
        full_name=full_name, phone=phone, address=address,
        items=[(pid, qty)]
    )

    # cashback
    cashback = 0
    if CASHBACK_PERCENT > 0:
        prod = db.get_product(pid)
        total = prod["price"] * qty
        cashback = (total * CASHBACK_PERCENT) // 100
        if cashback > 0:
            db.add_balance(user.id, cashback, "cashback", f"order:{order_id}")

    # notify admin
    admins = context.bot_data.get("ADMINS", [])
    for aid in admins:
        try:
            await context.bot.send_message(
                aid,
                f"سفارش جدید #{order_id}\n"
                f"کاربر: {full_name}\n"
                f"شماره: {phone}\n"
                f"آدرس: {address}\n"
                f"آیتم: #{pid} × {qty}\n"
                f"کش‌بک: {cashback} تومان"
            )
        except Exception:
            pass

    await update.message.reply_text("سفارش شما ثبت شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ---- Wallet / Topup
TOPUP_AMOUNT, TOPUP_NOTE = range(2)

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.get_wallet(update.effective_user.id)
    await update.message.reply_text(f"موجودی کیف پول شما: {bal} تومان.\nبرای شارژ: /topup")

async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مبلغ شارژ (تومان) را بفرستید:")
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(update.message.text.strip())
        if amt <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("مبلغ نامعتبر است. عدد مثبت وارد کنید.")
        return TOPUP_AMOUNT
    context.user_data["topup_amount"] = amt
    await update.message.reply_text("توضیح/روش (مثلاً کارت‌به‌کارت، چهار رقم آخر کارت و رسید):")
    return TOPUP_NOTE

async def topup_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    amt = context.user_data["topup_amount"]
    user_id = update.effective_user.id
    # ذخیره درخواست
    from .db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO topups(user_id, amount, method, note) VALUES(%s,%s,%s,%s) RETURNING id;",
            (user_id, amt, 'card', note)
        )
        tid = cur.fetchone()[0]
    # اطلاع به ادمین
    admins = context.bot_data.get("ADMINS", [])
    for aid in admins:
        try:
            await context.bot.send_message(
                aid,
                f"درخواست شارژ #{tid}\nکاربر: {user_id}\nمبلغ: {amt}\nروش: کارت‌به‌کارت\nیادداشت: {note}\n"
                f"برای تأیید: /approve_{tid}"
            )
        except Exception:
            pass
    await update.message.reply_text("درخواست شارژ ثبت شد و پس از تأیید ادمین اعمال می‌شود. ✅")
    return ConversationHandler.END

# دستورهای تأیید شارژ توسط ادمین به شکل /approve_123
async def approve_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    txt = update.message.text.strip()
    if not txt.startswith("/approve_"):
        return
    try:
        tid = int(txt.split("_", 1)[1])
    except Exception:
        return
    # پیدا و اعمال
    from .db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, amount, status FROM topups WHERE id=%s;", (tid,))
        r = cur.fetchone()
        if not r:
            await update.message.reply_text("درخواست یافت نشد.")
            return
        user_id, amount, status = r
        if status != "pending":
            await update.message.reply_text("این درخواست قبلاً رسیدگی شده است.")
            return
        cur.execute("UPDATE topups SET status='approved' WHERE id=%s;", (tid,))
    db.add_balance(user_id, amount, "topup", f"topup:{tid}")
    await update.message.reply_text(f"شارژ {amount} تومان برای کاربر {user_id} اعمال شد.")

# ---- Admin: add product
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(3)

async def addproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("اجازه دسترسی ندارید.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول:")
    return ADD_NAME

async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pname"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان):")
    return ADD_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        if price <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("قیمت نامعتبر است. دوباره عدد بفرستید.")
        return ADD_PRICE
    context.user_data["pprice"] = price
    await update.message.reply_text("لینک عکس (اختیاری). اگر ندارید، «-» بفرستید.")
    return ADD_PHOTO

async def addproduct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.text.strip()
    if photo == "-":
        photo = None
    pid = db.add_product(context.user_data["pname"], context.user_data["pprice"], photo)
    await update.message.reply_text(f"محصول ثبت شد. شناسه: #{pid}")
    return ConversationHandler.END

# ---- Game / Contact
async def game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(GAME_TEXT)

def build_conversations():
    # سفارش
    order_conv = ConversationHandler(
        entry_points=[CommandHandler("order", order_cmd)],
        states={
            ORDER_PICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_pick)],
            ORDER_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)],
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ORDER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            ORDER_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    # شارژ
    topup_conv = ConversationHandler(
        entry_points=[CommandHandler("topup", topup_start)],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_note)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    # افزودن محصول
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ADD_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_photo)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    return order_conv, topup_conv, add_conv

def build_handlers():
    h: List = []
    h.append(CommandHandler("start", start))
    h.append(CommandHandler("help", help_cmd))
    h.append(CommandHandler("products", products))
    h.append(CommandHandler("wallet", wallet))
    h.append(CommandHandler("contact", contact_enter))
    h.append(CommandHandler("game", game_cmd))
    h.append(MessageHandler(filters.Regex(r"^/approve_\d+$"), approve_router))
    order_conv, topup_conv, add_conv = build_conversations()
    h += [order_conv, topup_conv, add_conv]
    # پیام‌های دارک کانتکت
    h.append(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_to_admin))
    return h
