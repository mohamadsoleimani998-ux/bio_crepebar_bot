from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
from .base import log, ADMIN_IDS, CURRENCY, is_admin
from . import db

# ---------- Keyboards ----------
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("ℹ️ راهنما")],
    ], resize_keyboard=True
)

def fmt_price(x):  # تومان
    x = int(round(float(x)))
    return f"{x:,} {CURRENCY}"

# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.full_name or user.username or "-")
    db.ensure_categories()
    text = (
        "سلام 😊\n"
        "ربات فروشگاهی شما آماده است.\n"
        "از منوی زیر استفاده کنید."
    )
    await update.effective_message.reply_text(text, reply_markup=MAIN_KB)

# ---------- Menu (categories) ----------
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = db.list_categories()
    kb = [[InlineKeyboardButton(c, callback_data=f"cat::{c}") ] for c in cats]
    await update.effective_message.reply_text("دستهٔ محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))

# ---------- List products of a category with pagination ----------
async def on_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat = q.data.split("::",1)
    page = 1
    await send_products_page(q, cat, page)

async def send_products_page(cb_or_msg, cat:str, page:int):
    items, total = db.list_products(cat, page, page_size=6)
    rows = []
    for it in items:
        rows.append([InlineKeyboardButton(f"{it['name']} — {fmt_price(it['price'])}", callback_data=f"add::{it['id']}")])
    nav = []
    if page>1: nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"pg::{cat}::{page-1}"))
    if total > page*6: nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"pg::{cat}::{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="cart::show")])
    text = f"«{cat}»"
    if hasattr(cb_or_msg, "edit_message_text"):
        await cb_or_msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
    else:
        await cb_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))

async def on_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat, spage = q.data.split("::",2)
    await send_products_page(q, cat, int(spage))

# ---------- Add product to cart ----------
async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, sid = q.data.split("::",1)
    prod = db.get_product(int(sid))
    if not prod:
        await q.edit_message_text("محصول یافت نشد.")
        return
    user_row = db.by_tg(update.effective_user.id)
    oid = db.open_draft(user_row["id"])
    db.add_or_inc_item(oid, prod["id"], float(prod["price"]), 1)
    await q.answer("به سبد اضافه شد ✅", show_alert=False)

# ---------- Show cart ----------
async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; 
    if q: await q.answer()
    user_row = db.by_tg(update.effective_user.id)
    order, items = db.draft_with_items(user_row["id"])
    if not order or not items:
        msg = "سبد خالی است."
    else:
        lines = [f"🧾 سبد خرید:"]
        for it in items:
            lines.append(f"• {it['name']} × {it['qty']} = {fmt_price(it['line_total'])}")
        lines.append(f"— جمع کل: {fmt_price(order['total_amount'])}")
        msg = "\n".join(lines)
    if q:
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ ثبت سفارش", callback_data="order::submit")],
             [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back::menu")]]
        ))
    else:
        await update.effective_message.reply_text(msg)

async def on_back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await menu(update, context)

# ---------- Submit order (wallet only for now) ----------
async def order_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_row = db.by_tg(update.effective_user.id)
    order, items = db.draft_with_items(user_row["id"])
    if not order or not items:
        await q.edit_message_text("سبد خالی است.")
        return
    bal = db.balance(user_row["id"])
    if bal < float(order["total_amount"]):
        await q.edit_message_text(
            f"موجودی کیف پول کافی نیست.\n"
            f"جمع: {fmt_price(order['total_amount'])}\n"
            f"موجودی: {fmt_price(bal)}\n"
            "از مسیر «👛 کیف پول» شارژ کنید."
        )
        return
    # برداشت از کیف پول (tx منفی)
    db.credit(user_row["id"], -float(order["total_amount"]), kind="order", meta={"order_id": order["order_id"]})
    # وضعیت سفارش را پرداخت‌شده بگذاریم تا تریگر کش‌بک اعمال کند
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order["order_id"],))
    await q.edit_message_text("سفارش پرداخت شد ✅\nسپاس از خرید شما!")

# ---------- Wallet ----------
AMOUNT, RECEIPT = range(2)

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_row = db.by_tg(update.effective_user.id)
    bal = db.balance(user_row["id"])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 شارژ کارت‌به‌کارت", callback_data="topup::start")]])
    await update.effective_message.reply_text(
        f"موجودی شما: {fmt_price(bal)}\nکش‌بک فعال: 3٪", reply_markup=kb)

async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("مبلغ شارژ را به تومان بفرستید (مثلاً 150000):")
    return AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.effective_message.text.replace(",", "").strip())
        if amount <= 0: raise ValueError
    except Exception:
        await update.effective_message.reply_text("عدد معتبر وارد کنید:")
        return AMOUNT
    context.user_data["topup_amount"] = amount
    await update.effective_message.reply_text(
        "رسید/اسکرین‌شات واریز کارت‌به‌کارت را ارسال کنید (عکس).")
    return RECEIPT

async def topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس رسید را بفرستید.")
        return RECEIPT
    file_id = update.message.photo[-1].file_id
    amount = context.user_data.get("topup_amount")
    user_row = db.by_tg(update.effective_user.id)
    req_id = db.create_topup_request(user_row["id"], amount, file_id)

    # برای مدیر ارسال کنیم
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"adm_topup::{req_id}::ok"),
        InlineKeyboardButton("❌ رد",   callback_data=f"adm_topup::{req_id}::no"),
    ]])
    txt = f"درخواست شارژ جدید #{req_id}\nکاربر: {update.effective_user.full_name}\nمبلغ: {fmt_price(amount)}"
    for admin_id in ADMIN_IDS:
        try:
            await update.get_bot().send_photo(
                chat_id=admin_id, photo=file_id, caption=txt, reply_markup=kb)
        except Exception: pass

    await update.message.reply_text("درخواست شارژ ثبت شد ✅\nپس از تایید مدیر، موجودی شما افزایش می‌یابد.")
    return ConversationHandler.END

# --- Admin approve/decline topup ---
async def adm_topup_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(update.effective_user.id):
        await q.answer("فقط مدیر!", show_alert=True); return
    _, sid, action = q.data.split("::", 2)
    req_id = int(sid)
    # دریافت اطلاعات درخواست
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM topup_requests WHERE req_id=%s", (req_id,))
        r = cur.fetchone()
    if not r: 
        await q.edit_message_caption(caption="درخواست یافت نشد."); 
        return
    if action == "ok":
        db.credit(r["user_id"], float(r["amount"]), kind="topup", meta={"req_id": req_id})
        db.set_topup_status(req_id, "approved")
        await q.edit_message_caption(caption=f"✅ تایید شد و {fmt_price(r['amount'])} شارژ گردید.")
        # اطلاع به کاربر
        try:
            await update.get_bot().send_message(chat_id=(db.by_tg(r["user_id"]) or {}).get("telegram_id", None), text="شارژ کیف پول شما تایید شد ✅")
        except Exception: pass
    else:
        db.set_topup_status(req_id, "rejected")
        await q.edit_message_caption(caption="❌ رد شد.")

# ---------- Admin: add product (conversation) ----------
P_CAT, P_NAME, P_PRICE, P_DESC = range(10,14)

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("فقط مدیر!")
        return ConversationHandler.END
    cats = db.list_categories()
    kb = [[KeyboardButton(c)] for c in cats]
    await update.effective_message.reply_text("دسته را بفرست:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
    return P_CAT

async def add_product_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_cat"] = update.message.text.strip()
    await update.message.reply_text("نام محصول را بفرست:", reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True, one_time_keyboard=True))
    return P_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت به تومان:", reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True, one_time_keyboard=True))
    return P_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.replace(",", ""))
        if price<=0: raise ValueError
    except Exception:
        await update.message.reply_text("قیمت معتبر بفرست:")
        return P_PRICE
    context.user_data["p_price"] = price
    await update.message.reply_text("توضیح (اختیاری). اگر ندارید «-» بفرستید.")
    return P_DESC

async def add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-": desc = None
    pid = db.add_product(
        name=context.user_data["p_name"],
        price=context.user_data["p_price"],
        category=context.user_data["p_cat"],
        desc=desc
    )
    await update.message.reply_text(f"محصول ثبت شد ✅ (ID: {pid})", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ---------- router ----------
def build_handlers():
    # Conversations
    add_product_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", add_product_start)],
        states={
            P_CAT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_cat)],
            P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            P_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            P_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="add_product_conv", persistent=False
    )

    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_start, pattern=r"^topup::start$")],
        states={
            AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            RECEIPT: [MessageHandler(filters.PHOTO, topup_receipt)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="topup_conv", persistent=False
    )

    return [
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^🍭 منو$"), menu),
        MessageHandler(filters.Regex("^👛 کیف پول$"), wallet),
        MessageHandler(filters.Regex("^ℹ️ راهنما$"), start),
        MessageHandler(filters.Regex("^🧾 سفارش$"), show_cart),

        CallbackQueryHandler(on_cat, pattern=r"^cat::"),
        CallbackQueryHandler(on_page, pattern=r"^pg::"),
        CallbackQueryHandler(add_to_cart, pattern=r"^add::"),
        CallbackQueryHandler(show_cart, pattern=r"^cart::show$"),
        CallbackQueryHandler(on_back_menu, pattern=r"^back::menu$"),
        CallbackQueryHandler(order_submit, pattern=r"^order::submit$"),

        CallbackQueryHandler(adm_topup_action, pattern=r"^adm_topup::"),

        add_product_conv,
        topup_conv,
    ]
