from typing import List
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler
)
from .base import is_admin, CASHBACK_PERCENT
from . import db

# --- States for conversations ---
(ORDER_PICK_QTY, ORDER_GET_NAME, ORDER_GET_PHONE, ORDER_GET_ADDRESS) = range(4)
(TOPUP_AMOUNT, TOPUP_METHOD, CONTACT_WAIT) = range(4, 7)
(ADMIN_ADD_NAME, ADMIN_ADD_PRICE, ADMIN_ADD_IMG) = range(7, 10)
(ADMIN_EDIT_FIELD, ADMIN_EDIT_VALUE) = range(10, 12)

# --- Helpers ---
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["/products", "/wallet"],
        ["/order", "/help"],
        ["/contact", "/game"]
    ], resize_keyboard=True)

async def startup_warmup() -> None:
    db.init_db()

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_user(u.id, u.username or "", (u.full_name or "").strip())
    text = (
        "سلام! به ربات خوش آمدید.\n"
        "دستورات: /products , /wallet , /order , /help\n"
        "اگر ادمین هستید، برای افزودن محصول بعدا گزینهٔ ادمین اضافه می‌کنیم."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = "راهنما:\n/products نمایش منو\n/wallet کیف پول\n/order ثبت سفارش ساده"
    await update.message.reply_text(t, reply_markup=main_menu_kb())

async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارتباط با ما:\nپیام خود را بفرستید تا برای ادمین ارسال شود.")
    return CONTACT_WAIT

async def contact_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پیام کاربر را برای همه‌ی ادمین‌ها فوروارد کن
    for admin_id in context.bot_data.get("admin_ids", []):
        try:
            await update.message.forward(chat_id=admin_id)
        except Exception:
            pass
    await update.message.reply_text("پیام شما برای ادمین ارسال شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 بازی: به‌زودی…", reply_markup=main_menu_kb())

# --- Products ---
def _products_keyboard(products: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        rows.append([InlineKeyboardButton(f"{p['name']} - {p['price']} تومان", callback_data=f"p:{p['id']}")])
    if not rows:
        rows = [[InlineKeyboardButton("فعلا محصولی ثبت نشده", callback_data="noop")]]
    return InlineKeyboardMarkup(rows)

async def products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    await update.message.reply_text("منوی محصولات:", reply_markup=_products_keyboard(prods))

async def products_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if not data.startswith("p:"):
        return
    pid = int(data.split(":")[1])
    p = db.get_product(pid)
    if not p:
        await q.edit_message_text("این محصول موجود نیست.")
        return
    context.user_data["order_product_id"] = pid
    await q.edit_message_text(
        f"«{p['name']}» – {p['price']} تومان\n"
        f"چند عدد می‌خواهید؟ عدد را ارسال کنید."
    )
    return ORDER_PICK_QTY

# --- Order flow ---
async def order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اول لیست محصولات را بده
    prods = db.list_products()
    if not prods:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return ConversationHandler.END
    await update.message.reply_text("یک محصول انتخاب کنید:", reply_markup=_products_keyboard(prods))
    return ORDER_PICK_QTY  # بعد از انتخاب با کال‌بک برمی‌گردیم؛ اینجا فقط state می‌گذاریم

async def order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این حالت با هر دو مسیر می‌آید: یا از کال‌بک، یا عدد کاربر
    if update.callback_query:
        # اگر از کال‌بک بود، این تابع توسط products_cb ست شده و اینجا فقط منتظر عددیم
        await update.callback_query.answer()
        return ORDER_PICK_QTY

    msg = update.message.text.strip()
    if not msg.isdigit() or int(msg) <= 0:
        await update.message.reply_text("لطفاً فقط عدد مثبت بفرستید.")
        return ORDER_PICK_QTY

    context.user_data["order_qty"] = int(msg)
    await update.message.reply_text("نام و نام خانوادگی را بفرستید:")
    return ORDER_GET_NAME

async def order_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("شماره تماس را بفرستید:")
    return ORDER_GET_PHONE

async def order_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس کامل را بفرستید:")
    return ORDER_GET_ADDRESS

async def order_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text.strip()
    u = update.effective_user
    db.update_user_contact(u.id, phone=context.user_data["phone"], address=context.user_data["address"], full_name=context.user_data["name"])
    pid = context.user_data.get("order_product_id")
    qty = context.user_data.get("order_qty", 1)
    try:
        order_id, total, cashback = db.create_order(
            u.id, pid, qty, context.user_data["name"],
            context.user_data["phone"], context.user_data["address"]
        )
    except Exception as e:
        await update.message.reply_text(f"خطا در ثبت سفارش: {e}")
        return ConversationHandler.END

    # اطلاع به ادمین
    admins = context.bot_data.get("admin_ids", [])
    for aid in admins:
        try:
            await context.bot.send_message(
                aid,
                f"🛍 سفارش جدید #{order_id}\n"
                f"کاربر: {u.full_name} (@{u.username})\n"
                f"محصول: {pid} | تعداد: {qty}\n"
                f"جمع: {total} تومان\n"
                f"کش‌بک: {cashback} تومان"
            )
        except Exception:
            pass

    txt = (
        f"✅ سفارش شما ثبت شد.\n"
        f"شماره سفارش: #{order_id}\n"
        f"مبلغ: {total} تومان\n"
        + (f"کش‌بک شما: {cashback} تومان (٪{CASHBACK_PERCENT})\n" if CASHBACK_PERCENT else "")
        + "سپاس 🙏"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_kb())
    return ConversationHandler.END

# --- Wallet / Topup ---
async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    bal = db.get_wallet(u.id)
    await update.message.reply_text(f"موجودی کیف پول شما: {bal} تومان", reply_markup=main_menu_kb())

async def topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مبلغ شارژ (تومان) را بفرستید:")
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.isdigit() or int(t) <= 0:
        await update.message.reply_text("فقط عدد مثبت ارسال کنید.")
        return TOPUP_AMOUNT
    context.user_data["topup_amount"] = int(t)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("کارت به کارت", callback_data="t:card"), InlineKeyboardButton("درگاه (به‌زودی)", callback_data="t:gw")]
    ])
    await update.message.reply_text("روش شارژ را انتخاب کنید:", reply_markup=kb)
    return TOPUP_METHOD

async def topup_method_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = "card_to_card" if q.data == "t:card" else "gateway"
    u = update.effective_user
    topup_id = db.create_topup(u.id, context.user_data["topup_amount"], method)
    # پیام راهنما برای کارت به کارت
    txt = "درگاه به‌زودی فعال می‌شود.\n" if method == "gateway" else "لطفاً مبلغ را کارت به کارت کنید و رسید را برای ادمین بفرستید.\n"
    await q.edit_message_text(f"درخواست شارژ #{topup_id} ثبت شد. {txt}")
    # اطلاع به ادمین
    for aid in context.bot_data.get("admin_ids", []):
        try:
            await context.bot.send_message(aid, f"💳 درخواست شارژ #{topup_id} از کاربر {u.id} مبلغ {context.user_data['topup_amount']} تومان ({method})")
        except Exception:
            pass
    return ConversationHandler.END

# --- Admin: add/edit/delete products ---
async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("نام محصول را بفرستید:")
    return ADMIN_ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان) را بفرستید:")
    return ADMIN_ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.isdigit():
        await update.message.reply_text("فقط عدد بفرستید.")
        return ADMIN_ADD_PRICE
    context.user_data["p_price"] = int(t)
    await update.message.reply_text("لینک عکس (اختیاری) را بفرستید. اگر نمی‌خواهید بنویسید: -")
    return ADMIN_ADD_IMG

async def add_product_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    img = update.message.text.strip()
    if img == "-":
        img = None
    pid = db.add_product(context.user_data["p_name"], context.user_data["p_price"], img, True)
    await update.message.reply_text(f"✅ محصول با شناسه {pid} ذخیره شد.", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def edit_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("شناسه محصولی که می‌خواهید ویرایش کنید را بفرستید:")
    return ADMIN_EDIT_FIELD

async def edit_product_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.isdigit():
        await update.message.reply_text("شناسه عددی محصول را بفرستید.")
        return ADMIN_EDIT_FIELD
    context.user_data["edit_pid"] = int(t)
    await update.message.reply_text("کدام فیلد؟ (name / price / image / available)\nمقدار جدید را در پیام بعدی بفرستید.")
    return ADMIN_EDIT_VALUE

async def edit_product_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    pid = context.user_data["edit_pid"]
    # حداقل بررسی
    name = price = image = avail = None
    if value.lower() in {"true","false"}:
        avail = (value.lower() == "true")
    elif value.isdigit():
        price = int(value)
    elif value.startswith("http"):
        image = value
    else:
        name = value
    db.edit_product(pid, name=name, price=price, image_url=image, available=avail)
    await update.message.reply_text("✅ ویرایش انجام شد.", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def delete_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await update.message.reply_text("استفاده: /delete_product <product_id>")
        return
    db.delete_product(int(parts[1]))
    await update.message.reply_text("🗑 محصول حذف شد.", reply_markup=main_menu_kb())

# --- Handlers registry ---
def register(app):

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("products", products_cmd))
    app.add_handler(CallbackQueryHandler(products_cb, pattern=r"^p:\d+$"))
    app.add_handler(CommandHandler("order", order_cmd))
    # Order conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(products_cb, pattern=r"^p:\d+$"), CommandHandler("order", order_cmd)],
        states={
            ORDER_PICK_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)],
            ORDER_GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_name)],
            ORDER_GET_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_phone)],
            ORDER_GET_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_address)],
        },
        fallbacks=[]
    ))

    app.add_handler(CommandHandler("wallet", wallet_cmd))
    app.add_handler(CommandHandler("topup", topup_cmd))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("topup", topup_cmd)],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_METHOD: [CallbackQueryHandler(topup_method_cb, pattern=r"^t:(card|gw)$")],
        },
        fallbacks=[]
    ))

    app.add_handler(CommandHandler("contact", contact_cmd))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("contact", contact_cmd)],
        states={CONTACT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_forward)]},
        fallbacks=[]
    ))

    app.add_handler(CommandHandler("game", game_cmd))

    # Admin
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_product", add_product_cmd)],
        states={
            ADMIN_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADMIN_ADD_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADMIN_ADD_IMG:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_img)],
        },
        fallbacks=[]
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("edit_product", edit_product_cmd)],
        states={
            ADMIN_EDIT_FIELD:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_field)],
            ADMIN_EDIT_VALUE:[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_value)],
        },
        fallbacks=[]
    ))
    app.add_handler(CommandHandler("delete_product", delete_product_cmd))
