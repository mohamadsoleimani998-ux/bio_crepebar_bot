# src/handlers.py
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
from .base import log, fmt_money, is_admin, ADMIN_IDS, CARD_PAN, CARD_NAME, CARD_NOTE, CURRENCY, INSTAGRAM_URL
from . import db
import random

# ---------- Keyboards ----------
def main_keyboard():
    rows = [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("🎲 بازی روزانه")],
        [KeyboardButton("📱 اینستاگرام"), KeyboardButton("ℹ️ راهنما")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def categories_keyboard():
    cats = db.list_categories()
    # هر دسته -> دکمه
    buttons = [[InlineKeyboardButton(c["title"], callback_data=f"cat:{c['id']}")] for c in cats]
    return InlineKeyboardMarkup(buttons)

def product_list_markup(cat_id:int, items:list, page:int, total:int, page_size:int=6):
    btns = []
    # هر محصول دکمه افزودن
    for p in items:
        cap = f"➕ {p['name']} — {fmt_money(p['price'])}"
        btns.append([InlineKeyboardButton(cap, callback_data=f"add:{p['id']}")])
    # ناوبری
    nav = []
    if page>1:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"catp:{cat_id}:{page-1}"))
    if page*page_size < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"catp:{cat_id}:{page+1}"))
    if nav: btns.append(nav)
    # افزودن محصول (ادمین)
    btns.append([InlineKeyboardButton("➕ افزودن محصول (ادمین)", callback_data=f"addp:{cat_id}")])
    return InlineKeyboardMarkup(btns)

def cart_actions_markup(order_id:int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ثبت نهایی ✅", callback_data=f"submit:{order_id}")],
        [InlineKeyboardButton("خالی کردن 🧹", callback_data=f"empty:{order_id}")],
    ])

def pay_keyboard(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("پرداخت از کیف پول 👛", callback_data=f"payw:{order_id}")],
        [InlineKeyboardButton("کارت‌به‌کارت 🧾", callback_data=f"payc:{order_id}")],
    ])

# ---------- Conversations (Add Product & Topup & Register) ----------
(AP_NAME, AP_PRICE, AP_DESC, AP_PHOTO,
 TOPUP_AMOUNT, TOPUP_WAIT_RECEIPT,
 REG_WAIT_PHONE) = range(7)

# ----- start / register -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or "")
    # درخواست شماره موبایل اگر نداریم
    rec = db.get_user_by_tg(u.id)
    if not rec or not rec.get("phone"):
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("ارسال شماره ☎️", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await update.effective_chat.send_message(
            "سلام 😊\nبرای ثبت‌نام سریع، لطفاً شماره موبایل‌تان را ارسال کنید.",
            reply_markup=kb
        )
        return REG_WAIT_PHONE

    await update.effective_chat.send_message("سلام 😊\nربات فروشگاهی شما آماده است!", reply_markup=main_keyboard())

async def reg_got_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact and update.message.contact.phone_number:
        db.set_phone(update.effective_user.id, update.message.contact.phone_number)
        await update.message.reply_text("شماره شما ثبت شد ✅", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("لطفاً از دکمه «ارسال شماره ☎️» استفاده کنید.")
        return REG_WAIT_PHONE
    return ConversationHandler.END

# ----- Menu & Category -----
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("دستهٔ محصول را انتخاب کنید:", reply_markup=categories_keyboard())

async def cb_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id = q.data.split(":")
    await show_category(update, context, int(cat_id), 1)

async def cb_category_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id, page = q.data.split(":")
    await show_category(update, context, int(cat_id), int(page))

async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_id:int, page:int):
    page_size = 6
    items, total = db.list_products_by_category(cat_id, page, page_size)
    text = "در این دسته هنوز محصولی ثبت نشده." if not items else f"🧺 محصولات (صفحه {page})"
    markup = product_list_markup(cat_id, items, page, total, page_size)
    if update.callback_query:
        await update.effective_message.edit_text(text, reply_markup=markup)
    else:
        await update.effective_chat.send_message(text, reply_markup=markup)

# ----- Add product (admin) -----
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
    await update.message.reply_text("قیمت محصول را به **تومان** بفرستید (مثلاً 85000):", parse_mode="HTML")
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
    context.user_data["ap"]["desc"] = None if desc == "-" else desc
    await update.message.reply_text("عکس محصول را بفرستید (یا «-» برای رد):")
    return AP_PHOTO

async def ap_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ap = context.user_data.get("ap", {})
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    ap["photo"] = file_id
    pid = db.add_product(ap["cat_id"], ap["name"], ap["price"], ap["desc"], ap["photo"])
    await update.message.reply_text(f"✅ محصول «{ap['name']}» ثبت شد.")
    await show_category(update, context, ap["cat_id"], 1)
    return ConversationHandler.END

# ----- Add to cart -----
async def cb_add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, pid = q.data.split(":")
    prod = db.get_product(int(pid))
    if not prod:
        return await q.answer("محصول یافت نشد", show_alert=True)
    u = db.get_user_by_tg(update.effective_user.id)
    oid = db.open_draft_order(u["id"])
    db.add_or_increment_item(oid, prod["id"], float(prod["price"]), 1)
    await q.answer("به سبد اضافه شد ✅", show_alert=False)

# ----- Order / Cart / Checkout -----
async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order or not items:
        return await update.effective_chat.send_message("سبد شما خالی است. از «🍭 منو» محصول اضافه کنید.")
    lines = ["🧺 سبد شما:"]
    total = 0
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} = {fmt_money(it['line_total'])}")
        total += float(it['line_total'])
    lines.append(f"\nجمع کل: {fmt_money(total)}")
    await update.effective_chat.send_message("\n".join(lines), reply_markup=cart_actions_markup(order["order_id"]))

async def cb_empty_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    # حذف همه آیتم‌ها:
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE order_id=%s", (int(oid),))
        cur.execute("SELECT fn_recalc_order_total(%s)", (int(oid),))
    await q.edit_message_text("سبد خالی شد.")

async def cb_submit_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    db.submit_order(int(oid))
    await q.edit_message_text("ثبت شد ✅ لطفاً روش پرداخت را انتخاب کنید:", reply_markup=pay_keyboard(int(oid)))

async def cb_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    # برداشت از کیف پول
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT user_id,total_amount FROM orders WHERE order_id=%s", (int(oid),))
        row = cur.fetchone()
    if not row:
        return await q.edit_message_text("سفارش یافت نشد.")
    user_id, total = int(row["user_id"]), float(row["total_amount"])
    bal = db.get_balance(user_id)
    if bal < total:
        return await q.edit_message_text(f"موجودی کافی نیست. موجودی فعلی: {fmt_money(bal)}")
    db.add_wallet_tx(user_id, "order", -total, {"order_id": int(oid)})
    db.mark_order_paid(int(oid))  # تریگر کش‌بک اعمال می‌شود
    await q.edit_message_text(f"پرداخت موفق ✅\nمبلغ: {fmt_money(total)}\nکش‌بک به‌صورت خودکار اضافه می‌شود. سپاس!")

async def cb_pay_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    text = (
        f"🔻 اطلاعات کارت‌به‌کارت\n"
        f"• کارت: {CARD_PAN}\n• صاحب حساب: {CARD_NAME}\n{CARD_NOTE}\n\n"
        f"پس از واریز، از «👛 کیف پول» مبلغ را وارد و رسید را ارسال کنید؛ سپس ادمین تایید می‌کند."
    )
    await q.edit_message_text(text)

# ----- Wallet / Topup -----
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید ✅", callback_data=f"tpa:{req_id}")],
        [InlineKeyboardButton("رد ❌",   callback_data=f"tpr:{req_id}")],
    ])
    for admin_id in ADMIN_IDS:
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=update.message.photo[-1].file_id,
            caption=f"🔔 درخواست شارژ\nکاربر: {u['name']} ({u['telegram_id']})\nمبلغ: {fmt_money(amount)}\nreq_id={req_id}",
            reply_markup=kb
        )
    await update.message.reply_text("✅ درخواست شارژ ارسال شد. بعد از تایید ادمین، کیف پول شارژ می‌شود.")
    return ConversationHandler.END

async def cb_topup_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    approve = q.data.startswith("tpa:")
    req_id = int(q.data.split(":")[1])
    row = db.decide_topup(req_id, approve)
    if not row:
        return await q.edit_message_caption(caption="درخواست یافت نشد.")
    user_id, amount = int(row["user_id"]), float(row["amount"])
    if approve:
        db.add_wallet_tx(user_id, "topup", amount, {"req_id": req_id})
        await q.edit_message_caption(caption=f"✅ تایید شد و {fmt_money(amount)} شارژ شد.")
        # خبر به کاربر
        with db._conn() as cn, cn.cursor() as cur:
            cur.execute("SELECT telegram_id FROM users WHERE user_id=%s",(user_id,))
            tg = cur.fetchone()[0]
        await context.bot.send_message(tg, f"✅ شارژ تایید شد. مبلغ {fmt_money(amount)} به کیف پول شما اضافه شد.")
    else:
        await q.edit_message_caption(caption=f"❌ رد شد.")

# ----- Daily Game -----
async def daily_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    if not db.can_take_daily_bonus(u["id"]):
        return await update.effective_chat.send_message("امروز جایزه‌تان را گرفته‌اید. فردا دوباره تلاش کنید 😉")
    amount = random.choice([1000, 2000, 3000, 5000])
    if db.take_daily_bonus(u["id"], amount):
        await update.effective_chat.send_message(f"🎉 تبریک! {fmt_money(amount)} جایزه دریافت کردید و به کیف پول اضافه شد.")
    else:
        await update.effective_chat.send_message("متاسفانه خطایی رخ داد. دوباره امتحان کنید.")

# ----- Instagram / Help -----
async def instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(f"📱 اینستاگرام ما:\n{INSTAGRAM_URL}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "راهنما:\n"
        "• از «🍭 منو» دسته‌ها را ببینید و با دکمه‌ها به سبد اضافه کنید.\n"
        "• از «🧾 سفارش» سبد را ببینید و ثبت نهایی کنید.\n"
        "• پرداخت از «👛 کیف پول» یا «کارت‌به‌کارت» پشتیبانی می‌شود.\n"
        "• کش‌بک پس از پرداخت موفق به‌طور خودکار واریز می‌شود.\n"
        "• «🎲 بازی روزانه» هر روز یک جایزه‌ی کوچک به کیف پول می‌ریزد.\n"
        "• «📱 اینستاگرام» لینک صفحه را می‌دهد.",
        reply_markup=main_keyboard()
    )

# ---------- Builder ----------
def build_handlers():
    conv_register = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ REG_WAIT_PHONE: [MessageHandler(filters.CONTACT, reg_got_phone)] },
        fallbacks=[],
        name="register", persistent=False,
    )

    conv_add_product = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_product_entry, pattern=r"^addp:\d+$")],
        states={
            AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
            AP_PHOTO: [MessageHandler((filters.PHOTO | (filters.TEXT & ~filters.COMMAND)), ap_photo)],
        },
        fallbacks=[], name="add_product", persistent=False,
    )

    conv_topup = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👛 کیف پول$"), wallet)],
        states={
            TOPUP_AMOUNT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_WAIT_RECEIPT:  [MessageHandler(filters.PHOTO, topup_receipt)],
        },
        fallbacks=[], name="topup", persistent=False,
    )

    return [
        conv_register,
        MessageHandler(filters.Regex("^🍭 منو$"), menu),
        MessageHandler(filters.Regex("^🧾 سفارش$"), order_entry),
        MessageHandler(filters.Regex("^👛 کیف پول$"), wallet),    # میانبر
        MessageHandler(filters.Regex("^🎲 بازی روزانه$"), daily_game),
        MessageHandler(filters.Regex("^📱 اینستاگرام$"), instagram),
        MessageHandler(filters.Regex("^ℹ️ راهنما$"), help_cmd),

        CallbackQueryHandler(cb_category,      pattern=r"^cat:\d+$"),
        CallbackQueryHandler(cb_category_page, pattern=r"^catp:\d+:\d+$"),
        CallbackQueryHandler(cb_add_to_cart,   pattern=r"^add:\d+$"),
        CallbackQueryHandler(cb_submit_order,  pattern=r"^submit:\d+$"),
        CallbackQueryHandler(cb_empty_cart,    pattern=r"^empty:\d+$"),
        CallbackQueryHandler(cb_pay_wallet,    pattern=r"^payw:\d+$"),
        CallbackQueryHandler(cb_pay_card,      pattern=r"^payc:\d+$"),
        CallbackQueryHandler(lambda u,c: cb_topup_decide(u,c), pattern=r"^tp[ar]:\d+$"),

        conv_add_product,
        conv_topup,
    ]
