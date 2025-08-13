from math import ceil
from typing import List

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
)

from .base import log
from . import db

# ---------- تنظیمات نمایشی ----------
PAGE_SIZE = 6
CARD_NUMBER = "5029 0810 8098 4145"  # کارت به کارت

# ---------- کمک‌تابع‌ها ----------
def reply_kb():
    rows = [
        ["منو 🍭", "سفارش 🧾"],
        ["کیف پول 👛", "بازی 🎮"],
        ["ارتباط با ما ☎️", "راهنما ℹ️"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def fmt_price(x) -> str:
    try:
        v = int(float(x))
        return f"{v:,} تومان"
    except Exception:
        return str(x)

async def ensure_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u:
        db.upsert_user(u.id, u.full_name)

# ---------- منو محصولات ----------
def build_menu_kb(rows: List, page: int, total: int):
    max_page = max(1, ceil(total / PAGE_SIZE))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("« قبلی", callback_data=f"page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton("بعدی »", callback_data=f"page:{page+1}"))

    rows.append(nav)
    rows.append([InlineKeyboardButton("مشاهده فاکتور 🧾", callback_data="invoice")])
    return InlineKeyboardMarkup(rows)

async def send_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 1):
    prods, total = db.list_products(page, PAGE_SIZE)
    rows = []
    for p in prods:
        cap = f"{fmt_price(p['price'])} — {p['name']}"
        rows.append([InlineKeyboardButton(cap, callback_data=f"prd:{p['id']}")])
    kb = build_menu_kb(rows, page, total)
    text = "منو:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=kb)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb)

# ---------- فاکتور ----------
def render_invoice_text(order, items):
    if not order or not items:
        return "سبد شما خالی است."
    lines = [f"🧾 فاکتور سفارش #{order['order_id']}"]
    s = 0
    for it in items:
        line = f"• {it['name']} × {it['qty']} = {fmt_price(it['line_total'])}"
        s += float(it['line_total'] or 0)
        lines.append(line)
    lines.append(f"\nجمع کل: {fmt_price(s)}")
    lines.append("پرداخت: کیف پول یا پرداخت مستقیم")
    return "\n".join(lines)

def render_invoice_kb(items, order_id: int):
    rows = []
    for it in items:
        pid = it["product_id"]
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"dec:{pid}"),
            InlineKeyboardButton(f"{it['name']} × {it['qty']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"inc:{pid}")
        ])
    rows += [
        [InlineKeyboardButton("پرداخت از کیف‌ پول 👛", callback_data="payw")],
        [InlineKeyboardButton("پرداخت مستقیم 💳",  callback_data="payd")],
        [InlineKeyboardButton("خالی‌کردن سبد 🗑",   callback_data="clear")],
        [InlineKeyboardButton("بازگشت به منو 🍭",   callback_data="page:1")],
    ]
    return InlineKeyboardMarkup(rows)

async def show_invoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await ensure_user(update, ctx)
        user = db.get_user(update.effective_user.id)

    order, items = db.get_draft_with_items(user["id"])
    if not order:
        # ایجاد سفارش خالی جهت دکمه‌ها
        oid = db.open_draft_order(user["id"])
        order, items = db.get_draft_with_items(user["id"])

    kb = render_invoice_kb(items, order["order_id"]) if items else None
    text = render_invoice_text(order, items)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb)

# ---------- پرداخت ----------
async def pay_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    ok, msg = db.pay_order_wallet(user["id"])
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_chat.send_message(msg)
    # فاکتور را هم به‌روز کنیم
    await show_invoice(update, ctx)

async def pay_direct(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # دمو پرداخت مستقیم (نمایش کارت و درخواست ارسال رسید)
    txt = (
        "💳 پرداخت مستقیم (آزمایشی)\n"
        f"کارت به کارت به شماره:\n<b>{CARD_NUMBER}</b>\n\n"
        "پس از پرداخت، رسید را برای ما بفرستید تا سفارش تایید شود."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_html(txt)
    else:
        await update.effective_chat.send_message(txt, parse_mode="HTML")

# ---------- دستورات/پیام‌ها ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, ctx)
    text = (
        "سلام! 👋 به ربات بایو کِرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو 🍭: نمایش محصولات با نام و قیمت\n"
        "• سفارش 🧾: ثبت سفارش و مشاهده فاکتور\n"
        "• کیف پول 👛: مشاهده/شارژ، کش‌بک ۳٪ بعد هر خرید\n"
        "• بازی 🎮: سرگرمی\n"
        "• ارتباط با ما ☎️: پیام به ادمین\n"
        "• راهنما ℹ️: دستورات"
    )
    await update.effective_chat.send_message(text, reply_markup=reply_kb())

async def wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, ctx)
    user = db.get_user(update.effective_user.id)
    bal = db.get_balance(user["id"])
    txt = f"موجودی شما: {int(bal):,} تومان\nکش‌بک فعال: ۳٪"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="topup")],
        [InlineKeyboardButton("مشاهده فاکتور 🧾", callback_data="invoice")],
    ])
    await update.effective_chat.send_message(txt, reply_markup=kb)

async def wallet_topup_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (
        "برای شارژ کیف پول، فعلاً کارت‌به‌کارت:\n"
        f"<b>{CARD_NUMBER}</b>\n"
        "سپس مبلغ و رسید را ارسال کنید تا شارژ شود."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_html(txt)
    else:
        await update.effective_chat.send_message(txt, parse_mode="HTML")

async def help_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("راهنما: از دکمه‌های پایین استفاده کن.", reply_markup=reply_kb())

async def contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("پیام‌تان را ارسال کنید؛ ادمین بررسی می‌کند.")

# ---------- کال‌بک‌ها ----------
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()

    # ناوبری منو
    if data.startswith("page:"):
        page = int(data.split(":")[1])
        return await send_menu(update, ctx, page)

    # افزودن از منو
    if data.startswith("prd:"):
        pid = int(data.split(":")[1])
        user = db.get_user(update.effective_user.id)
        if not user:
            await ensure_user(update, ctx)
            user = db.get_user(update.effective_user.id)
        prod = db.get_product(pid)
        if not prod:
            return await q.message.reply_text("محصول در دسترس نیست.")
        oid = db.open_draft_order(user["id"])
        db.add_or_increment_item(oid, pid, float(prod["price"]), 1)
        await q.message.reply_text(f"«{prod['name']}» به سبد اضافه شد ✅")
        return

    # فاکتور
    if data == "invoice":
        return await show_invoice(update, ctx)

    # تغییر تعداد از فاکتور
    if data.startswith("inc:") or data.startswith("dec:"):
        pid = int(data.split(":")[1])
        user = db.get_user(update.effective_user.id)
        order, items = db.get_draft_with_items(user["id"])
        if not order:
            return await q.message.reply_text("سبد خالی است.")
        delta = +1 if data.startswith("inc:") else -1
        db.change_item_qty(order["order_id"], pid, delta)
        # بازنویسی فاکتور
        order, items = db.get_draft_with_items(user["id"])
        kb = render_invoice_kb(items, order["order_id"]) if items else None
        await q.edit_message_text(render_invoice_text(order, items), reply_markup=kb)
        return

    if data == "clear":
        user = db.get_user(update.effective_user.id)
        order, _ = db.get_draft_with_items(user["id"])
        if order:
            db.clear_order(order["order_id"])
        return await show_invoice(update, ctx)

    if data == "payw":
        return await pay_wallet(update, ctx)

    if data == "payd":
        return await pay_direct(update, ctx)

    if data == "topup":
        return await wallet_topup_info(update, ctx)

    # noop
    return

# ---------- پیام‌های متنی دکمه‌ها ----------
async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if t.startswith("منو"):
        return await send_menu(update, ctx, 1)
    if t.startswith("سفارش"):
        return await show_invoice(update, ctx)
    if t.startswith("کیف پول"):
        return await wallet(update, ctx)
    if t.startswith("راهنما"):
        return await help_msg(update, ctx)
    if t.startswith("ارتباط"):
        return await contact(update, ctx)
    return await update.effective_chat.send_message("از دکمه‌های پایین استفاده کن.", reply_markup=reply_kb())

# ---------- ثبت هندلرها ----------
def build_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
