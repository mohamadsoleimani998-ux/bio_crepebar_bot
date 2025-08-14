from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
from .base import log, fmt_money, is_admin, ADMIN_IDS, CARD_PAN, CARD_NAME, CARD_NOTE, CURRENCY
from . import db

# ---------- Keyboards ----------
def main_keyboard():
    from telegram import KeyboardButton, ReplyKeyboardMarkup
    rows = [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("ℹ️ راهنما")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def categories_keyboard():
    cats = db.list_categories()
    buttons = [[InlineKeyboardButton(c["title"], callback_data=f"cat:{c['id']}")] for c in cats]
    return InlineKeyboardMarkup(buttons)

def products_keyboard(cat_id: int, page: int, total: int, items, page_size: int = 6):
    buttons = []
    # دکمه‌ی هر محصول
    for p in items:
        buttons.append([InlineKeyboardButton(
            f"{p['name']} — {fmt_money(p['price'])}",
            callback_data=f"prod:{p['id']}"
        )])
    # صفحه‌بندی
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"catp:{cat_id}:{page-1}"))
    if page * page_size < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"catp:{cat_id}:{page+1}"))
    if nav:
        buttons.append(nav)
    # دکمه افزودن محصول برای ادمین
    buttons.append([InlineKeyboardButton("➕ افزودن محصول (ادمین)", callback_data=f"addp:{cat_id}")])
    return InlineKeyboardMarkup(buttons)

def cart_keyboard(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ثبت نهایی ✅", callback_data=f"submit:{order_id}")],
        [InlineKeyboardButton("خالی کردن 🧹", callback_data=f"empty:{order_id}")],
    ])

def pay_keyboard(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("پرداخت از کیف پول 👛", callback_data=f"payw:{order_id}")],
        [InlineKeyboardButton("کارت‌به‌کارت 🧾", callback_data=f"payc:{order_id}")],
    ])

# ---------- Conversations (Add Product & Topup) ----------
(
    AP_CAT, AP_NAME, AP_PRICE, AP_DESC, AP_PHOTO,
    TOPUP_AMOUNT, TOPUP_WAIT_RECEIPT
) = range(7)

# ----- /start -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or "")
    await update.effective_chat.send_message(
        "سلام 😊\nبه ربات فروشگاهی شما خوش آمدید!",
        reply_markup=main_keyboard()
    )

# ----- Menu -----
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("دستهٔ محصول را انتخاب کنید:", reply_markup=categories_keyboard())

# ----- Handle category -> show products page 1 -----
async def cb_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id = q.data.split(":")
    await show_category(update, context, int(cat_id), 1)

async def cb_category_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id, page = q.data.split(":")
    await show_category(update, context, int(cat_id), int(page))

async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_id: int, page: int):
    page_size = 6
    items, total = db.list_products_by_category(cat_id, page, page_size)
    txt = "در این دسته هنوز محصولی ثبت نشده است." if not items else f"🧺 محصولات (صفحه {page})"
    mark = products_keyboard(cat_id, page, total, items, page_size)
    if update.callback_query:
        await update.effective_message.edit_text(txt, reply_markup=mark)
    else:
        await update.effective_chat.send_message(txt, reply_markup=mark)

# ----- Product detail (when user taps a product) -----
async def cb_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, pid = q.data.split(":")
    row = db.get_product_by_id(int(pid))
    if not row:
        return await q.edit_message_text("❗️ محصول پیدا نشد.")
    txt = f"🛍 {row['name']}\n💵 {fmt_money(row['price'])}\n\n{row['description'] or ''}"
    await q.edit_message_text(txt)

# ----- Add product (admin only) -----
async def cb_add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id = q.data.split(":")
    if not is_admin(update.effective_user.id):
        return await q.edit_message_text("⛔️ فقط ادمین می‌تواند محصول اضافه کند.")
    context.user_data["ap"] = {"cat_id": int(cat_id)}
    await q.edit_message_text("نام محصول را بفرستید:")
    return AP_NAME

async def ap_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ap"]["name"] = update.message.text.strip()
    await update.message.reply_text("قیمت محصول را به <b>تومان</b> بفرستید (مثلاً 85000):", parse_mode="HTML")
    return AP_PRICE

async def ap_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").replace("،", "").strip())
    except Exception:
        return await update.message.reply_text("❗️ قیمت معتبر نیست؛ دوباره بفرست.")
    context.user_data["ap"]["price"] = price
    await update.message.reply_text("توضیح محصول (اختیاری). اگر ندارید «-» بفرستید:")
    return AP_DESC

async def ap_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-": desc = None
    context.user_data["ap"]["desc"] = desc
    await update.message.reply_text("عکس محصول را بفرستید (یا «-» برای رد):")
    return AP_PHOTO

async def ap_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ap = context.user_data.get("ap", {})
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    ap["photo"] = file_id
    pid = db.add_product(
        ap["cat_id"], ap["name"], ap["price"], ap["desc"], ap["photo"]
    )
    await update.message.reply_text(f"✅ محصول «{ap['name']}» ثبت شد.")
    # نمایش لیست همان دسته
    await show_category(update, context, ap["cat_id"], 1)
    return ConversationHandler.END

# ----- Wallet -----
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    bal = fmt_money(db.get_balance(u["id"]))
    txt = f"موجودی شما: {bal}\n\nکارت‌به‌کارت:\n• کارت: {CARD_PAN}\n• صاحب حساب: {CARD_NAME}\n{CARD_NOTE}\n\nبرای شارژ، مبلغ را بفرستید."
    await update.effective_chat.send_message(txt)
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.replace(",", "").replace("،", "").strip())
    except Exception:
        return await update.message.reply_text("❗️ مبلغ معتبر نیست؛ عدد بفرست.")
    context.user_data["topup_amount"] = amount
    await update.message.reply_text("✅ مبلغ دریافت شد. حالا عکس رسید را ارسال کنید.")
    return TOPUP_WAIT_RECEIPT

async def topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return await update.message.reply_text("لطفاً عکس رسید را بفرستید.")
    u = db.get_user_by_tg(update.effective_user.id)
    amount = context.user_data.get("topup_amount", 0)
    req_id = db.create_topup_request(u["id"], amount, update.message.message_id)

    # ارسال برای ادمین‌ها
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید ✅", callback_data=f"tpa:{req_id}")],
        [InlineKeyboardButton("رد ❌",   callback_data=f"tpr:{req_id}")],
    ])
    sent_ids = []
    for admin_id in ADMIN_IDS:
        msg = await context.bot.send_photo(
            chat_id=admin_id,
            photo=update.message.photo[-1].file_id,
            caption=f"🔔 درخواست شارژ جدید\nکاربر: {u['name']} ({u['telegram_id']})\nمبلغ: {fmt_money(amount)}\nreq_id={req_id}",
            reply_markup=kb
        )
        sent_ids.append(msg.message_id)
    if sent_ids:
        db.set_topup_admin_msg(req_id, sent_ids[0])

    await update.message.reply_text("✅ درخواست شارژ ارسال شد. پس از تایید ادمین، کیف پول شما شارژ می‌شود.")
    return ConversationHandler.END

async def cb_topup_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    approve = q.data.startswith("tpa:")
    req_id = int(q.data.split(":")[1])
    row = db.decide_topup(req_id, approve)
    if not row:
        return await q.edit_message_caption(caption="درخواست یافت نشد.")
    user_id, amount = int(row["user_id"]), float(row["amount"])
    # اعمال شارژ در صورت تایید
    if approve:
        db.add_wallet_tx(user_id, "topup", amount, {"req_id": req_id})
        await q.edit_message_caption(caption=f"✅ تایید شد و {fmt_money(amount)} شارژ شد.")
    else:
        await q.edit_message_caption(caption=f"❌ رد شد.")
    # اطلاع به کاربر
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT telegram_id FROM users WHERE user_id=%s", (user_id,))
        tg = cur.fetchone()[0]
    if approve:
        await context.bot.send_message(tg, f"✅ شارژ تایید شد. مبلغ {fmt_money(amount)} به کیف پول شما اضافه شد.")
    else:
        await context.bot.send_message(tg, f"❌ درخواست شارژ شما رد شد.")

# ----- Orders (ورود به منو سفارش) -----
async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await menu(update, context)

# ----- Help -----
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "راهنما:\n• از «🍭 منو» دسته‌ها را ببینید.\n• ادمین می‌تواند محصول اضافه کند.\n• از «👛 کیف پول» برای شارژ با کارت‌به‌کارت اقدام کنید.\n• پرداخت از کیف پول و کارت‌به‌کارت پشتیبانی می‌شود.",
        reply_markup=main_keyboard()
    )

# ---------- Builder ----------
def build_handlers():
    conv_add_product = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_product_entry, pattern=r"^addp:\d+$")],
        states={
            AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
            AP_PHOTO: [MessageHandler((filters.PHOTO | (filters.TEXT & ~filters.COMMAND)), ap_photo)],
        },
        fallbacks=[],
        name="add_product",
        persistent=False,
    )

    conv_topup = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👛 کیف پول$"), wallet)],
        states={
            TOPUP_AMOUNT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_WAIT_RECEIPT:  [MessageHandler(filters.PHOTO, topup_receipt)],
        },
        fallbacks=[],
        name="topup",
        persistent=False,
    )

    return [
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^🍭 منو$"), menu),
        MessageHandler(filters.Regex("^🧾 سفارش$"), order_entry),
        MessageHandler(filters.Regex("^👛 کیف پول$"), wallet),
        MessageHandler(filters.Regex("^ℹ️ راهنما$"), help_cmd),

        CallbackQueryHandler(cb_category,      pattern=r"^cat:\d+$"),
        CallbackQueryHandler(cb_category_page, pattern=r"^catp:\d+:\d+$"),
        CallbackQueryHandler(cb_product,       pattern=r"^prod:\d+$"),
        CallbackQueryHandler(cb_topup_decide,  pattern=r"^tp[ar]:\d+$"),

        conv_add_product,
        conv_topup,
    ]
