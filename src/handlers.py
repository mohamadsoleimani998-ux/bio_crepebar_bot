from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
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

def fmt_price(x):
    x = int(round(float(x)))
    return f"{x:,} {CURRENCY}"

# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.full_name or user.username or "-")
    db.ensure_categories()
    text = "سلام 😊\nاز منوی پایین استفاده کن."
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
    await send_products_page(q, cat, 1)

async def on_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat, spage = q.data.split("::",2)
    await send_products_page(q, cat, int(spage))

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

# ---------- Cart / Order ----------
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
    rm = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ ثبت سفارش", callback_data="order::submit")],
         [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back::menu")]]
    )
    if q: await q.edit_message_text(msg, reply_markup=rm)
    else:  await update.effective_message.reply_text(msg, reply_markup=rm)

async def on_back_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await menu(update, context)

async def order_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_row = db.by_tg(update.effective_user.id)
    order, items = db.draft_with_items(user_row["id"])
    if not order or not items:
        await q.edit_message_text("سبد خالی است."); return
    bal = db.balance(user_row["id"])
    if bal < float(order["total_amount"]):
        await q.edit_message_text(
            f"موجودی کافی نیست.\nجمع: {fmt_price(order['total_amount'])}\n"
            f"موجودی: {fmt_price(bal)}\nاز «👛 کیف پول» شارژ کنید."
        ); return
    db.credit(user_row["id"], -float(order["total_amount"]), kind="order", meta={"order_id": order["order_id"]})
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order["order_id"],))
    await q.edit_message_text("سفارش پرداخت شد ✅\nسپاس از خرید شما!")

# ---------- Wallet & Topup ----------
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
    await update.effective_message.reply_text("رسید/اسکرین‌شات واریز را ارسال کنید (عکس).")
    return RECEIPT

async def topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس رسید را بفرستید."); return RECEIPT
    file_id = update.message.photo[-1].file_id
    amount = context.user_data.get("topup_amount")
    user_row = db.by_tg(update.effective_user.id)
    req_id = db.create_topup_request(user_row["id"], amount, file_id)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"adm_topup::{req_id}::ok"),
        InlineKeyboardButton("❌ رد",   callback_data=f"adm_topup::{req_id}::no"),
    ]])
    txt = f"درخواست شارژ #{req_id}\nکاربر: {update.effective_user.full_name}\nمبلغ: {fmt_price(amount)}"
    for admin_id in ADMIN_IDS:
        try:
            await update.get_bot().send_photo(chat_id=admin_id, photo=file_id, caption=txt, reply_markup=kb)
        except Exception: pass

    await update.message.reply_text("درخواست ثبت شد ✅\nپس از تایید مدیر، موجودی شما افزایش می‌یابد.")
    return ConversationHandler.END

async def adm_topup_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(update.effective_user.id):
        await q.answer("فقط مدیر!", show_alert=True); return
    _, sid, action = q.data.split("::", 2)
    req_id = int(sid)
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM topup_requests WHERE req_id=%s", (req_id,))
        r = cur.fetchone()
    if not r:
        await q.edit_message_caption(caption="درخواست یافت نشد."); return
    if action == "ok":
        db.credit(r["user_id"], float(r["amount"]), kind="topup", meta={"req_id": req_id})
        db.set_topup_status(req_id, "approved")
        await q.edit_message_caption(caption=f"✅ تایید شد و {fmt_price(r['amount'])} شارژ گردید.")
    else:
        db.set_topup_status(req_id, "rejected")
        await q.edit_message_caption(caption="❌ رد شد.")

# ---------- Admin: Add product (conversation) ----------
P_CAT, P_NAME, P_PRICE, P_DESC = range(10,14)

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("فقط مدیر!"); return ConversationHandler.END
    cats = db.list_categories()
    kb = [[KeyboardButton(c)] for c in cats]
    await update.effective_message.reply_text(
        "دسته را بفرست:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
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
        await update.message.reply_text("قیمت معتبر بفرست:"); return P_PRICE
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

# ---------- Admin panel ----------
from psycopg2.extras import DictCursor

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("فقط مدیر!"); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن محصول", callback_data="adm::add")],
        [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="adm::products::1")],
        [InlineKeyboardButton("🗂 مدیریت دسته‌ها", callback_data="adm::cats")],
        [InlineKeyboardButton("💰 درخواست‌های شارژ معلق", callback_data="adm::topups::1")],
        [InlineKeyboardButton("🧾 سفارش‌ها (پرداخت‌شده)", callback_data="adm::orders::paid::1")],
        [InlineKeyboardButton("٪ تنظیم کش‌بک", callback_data="adm::cashback")],
    ])
    await update.effective_message.reply_text("پنل ادمین:", reply_markup=kb)

# products list
async def adm_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, spage = q.data.split("::")
    page=int(spage)
    items,total = db.list_products_admin(page=page, page_size=10)
    rows=[]
    for it in items:
        status = "✅" if it["is_active"] else "⛔"
        rows.append([InlineKeyboardButton(f"{status} {it['id']} | {it['name']} — {fmt_price(it['price'])}",
                                          callback_data=f"adm::product::{it['id']}")])
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("◀️", callback_data=f"adm::products::{page-1}"))
    if total>page*10: nav.append(InlineKeyboardButton("▶️", callback_data=f"adm::products::{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="adm::back")])
    await q.edit_message_text("مدیریت محصولات:", reply_markup=InlineKeyboardMarkup(rows))

async def adm_product_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    p = db.get_product(int(sid))
    if not p:
        await q.edit_message_text("یافت نشد."); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⤴️ تغییر قیمت", callback_data=f"adm::pprice::{p['id']}")],
        [InlineKeyboardButton("✅ فعال" if not p["is_active"] else "⛔ غیرفعال",
                              callback_data=f"adm::ptoggle::{p['id']}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"adm::pdel::{p['id']}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="adm::products::1")]
    ])
    await q.edit_message_text(f"{p['id']} — {p['name']} / {fmt_price(p['price'])}", reply_markup=kb)

# ask price
ASK_PRICE = 50
async def adm_ask_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    context.user_data["pid_change_price"]=int(sid)
    await q.edit_message_text("قیمت جدید را بفرست (تومان):")
    return ASK_PRICE

async def adm_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val=float(update.message.text.replace(",",""))
    except Exception:
        await update.message.reply_text("مقدار معتبر نیست، دوباره ارسال کنید:"); return ASK_PRICE
    pid=context.user_data.pop("pid_change_price")
    db.update_price(pid, val)
    await update.message.reply_text("قیمت بروزرسانی شد ✅")
    return ConversationHandler.END

async def adm_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    p = db.get_product(int(sid)); 
    db.set_product_active(p["id"], not p["is_active"])
    await q.edit_message_text("وضعیت تغییر کرد ✅")

async def adm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    db.delete_product(int(sid))
    await q.edit_message_text("حذف شد ✅")

# categories
async def adm_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    cats = db.list_categories()
    rows=[[InlineKeyboardButton(f"➖ {c}", callback_data=f"adm::catdel::{c}") ] for c in cats]
    rows.append([InlineKeyboardButton("➕ افزودن دسته", callback_data="adm::catadd")])
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="adm::back")])
    await q.edit_message_text("مدیریت دسته‌ها:", reply_markup=InlineKeyboardMarkup(rows))

CAT_NAME = 60
async def adm_cat_add_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("نام دستهٔ جدید را بفرست:")
    return CAT_NAME

async def adm_cat_add_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name=update.message.text.strip()
    db.add_category(name)
    await update.message.reply_text("دسته اضافه شد ✅"); 
    return ConversationHandler.END

async def adm_cat_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, name = q.data.split("::",2)
    db.del_category(name)
    await q.edit_message_text("حذف شد ✅")

# cashback
CASHBACK_SET = 70
async def adm_cashback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    await q.edit_message_text("درصد کش‌بک جدید را بفرست (مثلاً 3):")
    return CASHBACK_SET

async def adm_cashback_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p=float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("عددی بفرست (مثلاً 3):"); return CASHBACK_SET
    db.set_cashback(p)
    await update.message.reply_text("ذخیره شد ✅")
    return ConversationHandler.END

# list pending topups
async def adm_topups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, spage = q.data.split("::")
    page=int(spage)
    items,total = db.list_topups(status='pending', page=page, page_size=6)
    if not items:
        await q.edit_message_text("صف خالی است."); return
    rows=[]
    for r in items:
        rows.append([InlineKeyboardButton(f"#{r['req_id']} — {fmt_price(r['amount'])}", callback_data=f"adm_topup_open::{r['req_id']}")])
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("◀️", callback_data=f"adm::topups::{page-1}"))
    if total>page*6: nav.append(InlineKeyboardButton("▶️", callback_data=f"adm::topups::{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="adm::back")])
    await q.edit_message_text("درخواست‌های معلق:", reply_markup=InlineKeyboardMarkup(rows))

async def adm_topup_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    req_id=int(sid)
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM topup_requests WHERE req_id=%s", (req_id,))
        r=cur.fetchone()
    if not r: await q.edit_message_text("یافت نشد."); return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"adm_topup::{req_id}::ok"),
        InlineKeyboardButton("❌ رد",   callback_data=f"adm_topup::{req_id}::no"),
    ], [InlineKeyboardButton("🔙", callback_data="adm::topups::1")]])
    # نمایش عکس
    try:
        await q.message.reply_photo(photo=r["photo_file_id"], caption=f"#{r['req_id']} مبلغ: {fmt_price(r['amount'])}", reply_markup=kb)
        await q.edit_message_text("پیش‌نمایش رسید بالا ارسال شد.")
    except Exception:
        await q.edit_message_text("عدم دسترسی به عکس، فقط دکمه‌ها:", reply_markup=kb)

# orders
async def adm_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, status, spage = q.data.split("::")
    page=int(spage)
    items,total = db.list_orders(status=status, page=page, page_size=10)
    rows=[]
    for r in items:
        rows.append([InlineKeyboardButton(f"#{r['order_id']} | {r['status']} | {fmt_price(r['total_amount'])}", callback_data=f"adm::order::{r['order_id']}")])
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("◀️", callback_data=f"adm::orders::{status}::{page-1}"))
    if total>page*10: nav.append(InlineKeyboardButton("▶️", callback_data=f"adm::orders::{status}::{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="adm::back")])
    await q.edit_message_text(f"سفارش‌ها ({status}):", reply_markup=InlineKeyboardMarkup(rows))

async def adm_order_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, sid = q.data.split("::")
    oid=int(sid)
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("به ‘fulfilled’", callback_data=f"adm::orderst::{oid}::fulfilled")],
        [InlineKeyboardButton("به ‘canceled’",  callback_data=f"adm::orderst::{oid}::canceled")],
        [InlineKeyboardButton("🔙", callback_data="adm::orders::paid::1")]
    ])
    await q.edit_message_text(f"سفارش #{oid}", reply_markup=kb)

async def adm_order_set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, _, sid, newst = q.data.split("::")
    db.set_order_status(int(sid), newst)
    await q.edit_message_text("وضعیت بروزرسانی شد ✅")

# ---------- routers ----------
def build_handlers():
    # Conversations
    add_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: add_product_start(u,c), pattern=r"^adm::add$"),
                      CommandHandler("addproduct", add_product_start)],
        states={
            P_CAT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_cat)],
            P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            P_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            P_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="add_product_conv", persistent=False
    )

    price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_ask_price, pattern=r"^adm::pprice::")],
        states={ ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_set_price)] },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="price_conv", persistent=False
    )

    cat_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_cat_add_q, pattern=r"^adm::catadd$")],
        states={ 60: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_cat_add_set)] },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="cat_add_conv", persistent=False
    )

    cashback_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_cashback, pattern=r"^adm::cashback$")],
        states={ 70: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_cashback_set)] },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="cashback_conv", persistent=False
    )

    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_start, pattern=r"^topup::start$")],
        states={ AMOUNT:[MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
                 RECEIPT:[MessageHandler(filters.PHOTO, topup_receipt)] },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
        name="topup_conv", persistent=False
    )

    return [
        # user
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
        CallbackQueryHandler(adm_topup_open,   pattern=r"^adm_topup_open::"),

        # admin panel
        CommandHandler("admin", admin_menu),
        CallbackQueryHandler(admin_menu, pattern=r"^adm::back$"),
        CallbackQueryHandler(adm_products, pattern=r"^adm::products::"),
        CallbackQueryHandler(adm_product_actions, pattern=r"^adm::product::"),
        CallbackQueryHandler(adm_toggle, pattern=r"^adm::ptoggle::"),
        CallbackQueryHandler(adm_delete, pattern=r"^adm::pdel::"),
        CallbackQueryHandler(adm_cats, pattern=r"^adm::cats$"),
        CallbackQueryHandler(adm_cat_del, pattern=r"^adm::catdel::"),
        CallbackQueryHandler(adm_topups, pattern=r"^adm::topups::"),
        CallbackQueryHandler(adm_orders, pattern=r"^adm::orders::"),
        CallbackQueryHandler(adm_order_actions, pattern=r"^adm::order::"),
        CallbackQueryHandler(adm_order_set_status, pattern=r"^adm::orderst::"),

        # conversations
        add_product_conv, price_conv, cat_add_conv, cashback_conv, topup_conv,
    ]
