from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from .base import ADMIN_IDS, log
from . import db_sqlite as db

# ---------- Keyboards ----------
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("ℹ️ راهنما")],
    ],
    resize_keyboard=True
)

def format_toman(n: int) -> str:
    s = f"{n:,}".replace(",", "،")
    return f"{s} تومان"

# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name)
    await update.message.reply_html(
        "سلام 🙂\nربات فروشگاهی شما آماده است!\nاز دکمه‌های پایین استفاده کن.",
        reply_markup=MAIN_KB
    )

# ---------- Menu / Categories ----------
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = db.list_categories()
    rows = []
    for c in cats:
        rows.append([InlineKeyboardButton(c["name"], callback_data=f"cat:{c['category_id']}")])
    rows.append([InlineKeyboardButton("➕ افزودن محصول (ادمین)", callback_data="admin:add")])
    await update.effective_message.reply_text("دسته‌بندی‌ها:", reply_markup=InlineKeyboardMarkup(rows))

async def cbquery_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("cat:"):
        cat_id = int(data.split(":",1)[1])
        await show_products(q, context, cat_id)
    elif data.startswith("prod:"):
        _, prod_id = data.split(":")
        await add_product_to_cart(q, context, int(prod_id))
    elif data == "admin:add":
        await begin_add_product(q, context)

async def show_products(src, context: ContextTypes.DEFAULT_TYPE, cat_id: int):
    prods = db.list_products(cat_id)
    if not prods:
        await src.edit_message_text("هنوز محصولی در این دسته ثبت نشده.")
        return
    rows = []
    for p in prods:
        cap = f"{p['name']} — {format_toman(p['price'])}"
        rows.append([InlineKeyboardButton(cap, callback_data=f"prod:{p['product_id']}")])
    await src.edit_message_text("محصولات:", reply_markup=InlineKeyboardMarkup(rows))

async def add_product_to_cart(src, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    u = src.from_user
    user = db.get_user_by_tg(u.id)
    if not user:
        db.upsert_user(u.id, u.full_name)
        user = db.get_user_by_tg(u.id)
    prod = db.get_product(product_id)
    if not prod:
        await src.answer("محصول ناموجود است", show_alert=True)
        return
    oid = db.open_draft_order(user["user_id"])
    db.add_or_inc_item(oid, product_id, prod["price"], 1)
    await src.answer("به سبد اضافه شد ✅", show_alert=False)

# ---------- Wallet ----------
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    bal = u["balance"] if u else 0
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 شارژ کارت‌به‌کارت", callback_data="wallet:topup")],
    ])
    await update.effective_message.reply_html(
        f"موجودی شما: <b>{format_toman(bal)}</b>\nکش‌بک فعال: <b>%</b>",
        reply_markup=kb
    )

async def wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet:topup":
        await q.edit_message_text(
            "برای شارژ کارت‌به‌کارت:\n"
            "۱) مبلغ دلخواه را کارت‌به‌کارت کنید.\n"
            "۲) رسید یا مبلغ را برای ادمین بفرستید.\n"
            "ادمین پس از تایید، کیف پول را شارژ می‌کند."
        )

# ---------- Order / Invoice ----------
def render_invoice(order, items) -> str:
    if not order:
        return "سبد شما خالی است."
    lines = ["<b>فاکتور شما</b>"]
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} = {format_toman(it['qty']*it['unit_price'])}")
    lines.append(f"\nجمع کل: <b>{format_toman(order['total_amount'])}</b>")
    return "\n".join(lines)

async def order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    if not u:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name)
        u = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(u["user_id"])
    if not items:
        await update.effective_message.reply_text("سبد شما خالی است.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ پرداخت از کیف پول", callback_data="chk:wallet")],
        [InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="chk:card")],
    ])
    await update.effective_message.reply_html(render_invoice(order, items), reply_markup=kb)

async def checkout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = db.get_user_by_tg(q.from_user.id)
    order, items = db.get_draft_with_items(u["user_id"])
    if not order:
        await q.edit_message_text("سبد شما خالی است.")
        return
    if q.data == "chk:wallet":
        ok = db.pay_order_wallet(u["user_id"], order["order_id"])
        if not ok:
            await q.edit_message_text("موجودی کافی نیست. از منوی «کیف پول» شارژ کنید.")
            return
        await q.edit_message_text("پرداخت شد ✅\nسفارش شما ثبت گردید.")
    else:
        db.submit_order(order["order_id"])
        await q.edit_message_text(
            "روش کارت‌به‌کارت انتخاب شد.\n"
            "لطفاً مبلغ فاکتور را واریز کنید و رسید را برای ادمین ارسال نمایید.\n"
            "پس از تایید، وضعیت پرداخت تکمیل می‌شود.🙏"
        )

# ---------- Admin: add product ----------
ADD_CAT, ADD_NAME, ADD_PRICE = range(3)

async def begin_add_product(src, context: ContextTypes.DEFAULT_TYPE):
    if src.from_user.id not in ADMIN_IDS:
        await src.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    context.user_data["add"] = {}
    cats = db.list_categories()
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"addcat:{c['category_id']}")] for c in cats]
    await src.edit_message_text("دستهٔ محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(rows))
    return ADD_CAT

async def add_cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("addcat:"):
        cid = int(data.split(":")[1])
        context.user_data.setdefault("add", {})["cat"] = cid
        await q.edit_message_text("نام محصول را بفرستید:")
        return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add"]["name"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("قیمت (تومان) را بفرستید:")
    return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.effective_message.text.strip().replace(",", "").replace("،", "")
    if not txt.isdigit():
        await update.effective_message.reply_text("فقط عدد قیمت را بفرست.")
        return ADD_PRICE
    price = int(txt)
    data = context.user_data["add"]
    pid = db.add_product(data["cat"], data["name"], price)
    await update.effective_message.reply_html(f"محصول ثبت شد ✅ (ID: <code>{pid}</code>)")
    return ConversationHandler.END

def build_handlers():
    conv_add = ConversationHandler(
        entry_points=[],
        states={
            ADD_CAT:   [CallbackQueryHandler(add_cb_router, pattern=r"^addcat:")],
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
        },
        fallbacks=[],
        name="addproduct",
        persistent=False,
    )
    return [
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^🍭 منو$") | filters.Regex("^منو$"), show_menu),
        MessageHandler(filters.Regex("^👛 کیف پول$") | filters.Regex("^کیف پول$"), wallet),
        MessageHandler(filters.Regex("^🧾 سفارش$") | filters.Regex("^سفارش$"), order_cmd),
        CallbackQueryHandler(cbquery_router, pattern=r"^(cat:|prod:|admin:add)$"),
        CallbackQueryHandler(wallet_cb, pattern=r"^wallet:"),
        CallbackQueryHandler(checkout_cb, pattern=r"^chk:"),
        conv_add,
    ]
