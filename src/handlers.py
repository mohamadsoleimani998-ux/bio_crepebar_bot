from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)

from .base import log
from . import db

# ------------ کمک‌ها
CURRENCY = "تومان"

def money(n):
    try:
        return f"{int(n):,} {CURRENCY}"
    except:
        return f"{n} {CURRENCY}"

def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in r] for r in rows])

# ------------ رندر دسته‌ها و محصولات
async def show_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cats = db.list_categories()
    rows, row = [], []
    for i, c in enumerate(cats, start=1):
        row.append((c["name"], f"c:{c['id']}:1"))  # صفحه 1
        if i % 2 == 0:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([("🛒 سبد خرید", "cart")])
    await update.effective_chat.send_message(
        "منو:", reply_markup=kb(rows)
    )

async def show_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int, page: int):
    page_size = 6
    items, total = db.list_products(cat_id, page, page_size)
    if not items:
        await update.effective_chat.send_message("محصولی در این دسته ثبت نشده است.")
        return
    rows = []
    for it in items:
        title = f"{it['name']} — {money(it['price'])}"
        rows.append([(title, f"p:{it['id']}:a")])  # کلیک = افزودن 1 عدد
    # صفحه‌بندی
    pages = max(1, (total + page_size - 1)//page_size)
    nav = []
    if page > 1: nav.append(("« قبلی", f"c:{cat_id}:{page-1}"))
    nav.append((f"{page}/{pages}", "noop"))
    if page < pages: nav.append(("بعدی »", f"c:{cat_id}:{page+1}"))
    rows.append(nav)
    rows.append([("🛒 سبد خرید", "cart"), ("↩️ دسته‌ها", "cats")])
    if update.callback_query:
        await update.callback_query.edit_message_text("محصولات:", reply_markup=kb(rows))
    else:
        await update.effective_chat.send_message("محصولات:", reply_markup=kb(rows))

# ------------ سبد خرید/سفارش
def _cart_text(order, items):
    lines = ["<b>سبد خرید</b>\n"]
    if not items:
        lines.append("سبد خالی است.")
    else:
        for it in items:
            lines.append(f"• {it['name']} × {it['qty']} = {money(it['line_total'])}")
        lines.append(f"\n<b>جمع کل:</b> {money(order['total_amount'])}")
    return "\n".join(lines)

async def show_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    if not u:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name)
        u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order:
        order_id = db.open_draft_order(u["id"])
        order, items = db.get_draft_with_items(u["id"])
    rows = []
    if items:
        rows.append([("✅ پرداخت از کیف پول", "pay:w"), ("💳 کارت‌به‌کارت", "pay:t")])
        rows.append([("🗑 خالی کردن سبد", "cart:clear")])
    rows.append([("↩️ دسته‌ها", "cats")])
    text = _cart_text(order, items)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb(rows), parse_mode=ParseMode.HTML)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb(rows), parse_mode=ParseMode.HTML)

# ------------ پرداخت
async def handle_pay(update: Update, ctx: ContextTypes.DEFAULT_TYPE, kind: str):
    u = db.get_user(update.effective_user.id)
    if not u:
        await update.effective_chat.send_message("ابتدا /start را ارسال کنید.")
        return
    order, items = db.get_draft_with_items(u["id"])
    if not order or not items:
        await update.effective_chat.send_message("سبد خالی است.")
        return

    if kind == "w":  # wallet
        ok = db.pay_from_wallet(u["id"], order["order_id"])
        if not ok:
            bal = db.get_balance(u["id"])
            await update.effective_chat.send_message(
                f"موجودی کیف پول کافی نیست.\nموجودی فعلی: {money(bal)}"
            )
            return
        await update.effective_chat.send_message("✅ سفارش با موفقیت از کیف پول پرداخت شد.")
    else:  # transfer/card-to-card
        db.submit_order(order["order_id"], note="در انتظار بررسی کارت‌به‌کارت")
        await update.effective_chat.send_message(
            "✅ سفارش ثبت شد.\nلطفاً مبلغ را کارت‌به‌کارت کنید و رسید را برای ادمین ارسال نمایید."
        )
    await show_cart(update, ctx)

# ------------ کال‌بک‌کوئری
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    if data == "cats":
        await show_categories(update, ctx)
        return
    if data.startswith("c:"):
        # c:<cat_id>:<page>
        _, cid, pg = data.split(":")
        await show_products(update, ctx, int(cid), int(pg))
        return
    if data.startswith("p:"):
        # p:<product_id>:a  -> add 1
        _, pid, action = data.split(":")
        u = db.get_user(update.effective_user.id)
        if not u:
            db.upsert_user(update.effective_user.id, update.effective_user.full_name)
            u = db.get_user(update.effective_user.id)
        prod = db.get_product(int(pid))
        if not prod:
            await q.answer("ناموجود", show_alert=True)
            return
        oid = db.open_draft_order(u["id"])
        db.add_or_increment_item(oid, prod["id"], float(prod["price"]), 1)
        await q.answer("افزوده شد ✅")
        return
    if data == "cart":
        await show_cart(update, ctx)
        return
    if data == "cart:clear":
        u = db.get_user(update.effective_user.id)
        if u:
            order, items = db.get_draft_with_items(u["id"])
            if order:
                db.clear_cart(order["order_id"])
        await show_cart(update, ctx)
        return
    if data.startswith("pay:"):
        _, kind = data.split(":")
        await handle_pay(update, ctx, kind)
        return
    # دکمه نمایشی
    if data == "noop":
        return

# ------------ فرمان‌ها/پیام‌ها
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.full_name)
    await update.message.reply_text("سلام 😊\nاز دکمهٔ «منو» استفاده کن.", reply_markup=None)
    await show_categories(update, ctx)

async def msg_menu_word(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # اگر کاربر «منو» بفرستد
    await show_categories(update, ctx)

def build_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Regex(r"^(منو|/menu)$"), msg_menu_word))
