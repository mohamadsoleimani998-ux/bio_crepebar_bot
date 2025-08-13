from __future__ import annotations

import math
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from .base import log, CASHBACK_PERCENT
from . import db

# ---------------------------
# کمک‌ها
# ---------------------------
BTN_MENU = "منو 🍭"
BTN_ORDER = "سفارش 🧾"
BTN_WALLET = "کیف پول 👛"
BTN_HELP = "راهنما ℹ️"
BTN_CONTACT = "ارتباط با ما ☎️"
BTN_GAME = "بازی 🎮"

PAGE_SIZE = 6  # تعداد محصول در هر صفحه

def toman(n: float | int) -> str:
    try:
        v = int(n)
        return f"{v:,} تومان"
    except Exception:
        return f"{n} تومان"

def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_MENU), KeyboardButton(BTN_ORDER)],
        [KeyboardButton(BTN_WALLET), KeyboardButton(BTN_GAME)],
        [KeyboardButton(BTN_CONTACT), KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ---------------------------
# /start
# ---------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u:
        db.upsert_user(u.id, (u.full_name or "").strip())
    text = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        f"• {BTN_MENU}: نمایش محصولات با نام و قیمت\n"
        f"• {BTN_ORDER}: ثبت سفارش و مشاهده فاکتور\n"
        f"• {BTN_WALLET}: مشاهده/شارژ، کش‌بک {CASHBACK_PERCENT}% بعد هر خرید\n"
        f"• {BTN_GAME}: سرگرمی\n"
        f"• {BTN_CONTACT}: پیام به ادمین\n"
        f"• {BTN_HELP}: دستورات"
    )
    await update.effective_chat.send_message(text, reply_markup=main_keyboard())

# ---------------------------
# منوی محصولات (لیست و صفحه‌بندی)
# ---------------------------
def build_products_markup(page: int = 1) -> InlineKeyboardMarkup:
    products, total = db.list_products(page=page, page_size=PAGE_SIZE)
    buttons: list[list[InlineKeyboardButton]] = []
    for p in products:
        # متن دکمه: «قیمت — نام»
        txt = f"{toman(p['price'])} — {p['name']}"
        buttons.append([InlineKeyboardButton(txt, callback_data=f"p:add:{p['id']}")])

    # ناوبری
    pages = max(1, math.ceil(total / PAGE_SIZE))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"p:page:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"p:page:{page+1}"))
    if nav:
        buttons.append(nav)

    # دکمه فاکتور
    buttons.append([InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="inv:view")])

    return InlineKeyboardMarkup(buttons)

async def show_menu_message(update: Update, page: int = 1):
    chat = update.effective_chat
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text="منو:",
            reply_markup=build_products_markup(page),
        )
        await update.callback_query.answer()
    else:
        await chat.send_message("منو:", reply_markup=build_products_markup(page))

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu_message(update, page=1)

async def cb_menu_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, _, s_page = q.data.split(":")
    page = max(1, int(s_page))
    await show_menu_message(update, page=page)

# افزودن محصول به سبد
async def cb_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, _, s_id = q.data.split(":")
    pid = int(s_id)
    user = update.effective_user
    if not user:
        await q.answer("کاربر نامشخص", show_alert=True)
        return

    db.upsert_user(user.id, (user.full_name or "").strip())
    urow = db.get_user(user.id)
    if not urow:
        await q.answer("کاربر یافت نشد.", show_alert=True)
        return

    p = db.get_product(pid)
    if not p:
        await q.answer("این محصول موجود نیست.", show_alert=True)
        return

    oid = db.open_draft_order(urow["id"])
    db.add_or_increment_item(oid, p["id"], float(p["price"]), inc=1)

    await q.answer("به سبد اضافه شد ✅", show_alert=False)

# ---------------------------
# فاکتور + ویرایش سبد
# ---------------------------
def build_invoice_text_and_markup(user_id: int):
    order, items = db.get_draft_with_items(user_id)
    if not order:
        return "سبد شما خالی است.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("بازگشت به منو", callback_data="p:page:1")]]
        )

    lines = ["🧾 فاکتور جاری:"]
    for it in items:
        lines.append(
            f"• {it['name']} × {it['qty']} = {toman(it['line_total'])}"
        )
    lines.append(f"\nجمع کل: <b>{toman(order['total_amount'])}</b>")
    text = "\n".join(lines)

    # دکمه‌های +/− و پرداخت
    kb: list[list[InlineKeyboardButton]] = []
    for it in items:
        kb.append([
            InlineKeyboardButton("➖", callback_data=f"cart:dec:{it['product_id']}"),
            InlineKeyboardButton(f"{it['name']} × {it['qty']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:inc:{it['product_id']}"),
        ])

    kb.append([InlineKeyboardButton("🔄 بازگشت به منو", callback_data="p:page:1")])
    kb.append([
        InlineKeyboardButton("💳 پرداخت از کیف پول", callback_data="cart:pay:wallet"),
        InlineKeyboardButton("💵 پرداخت مستقیم (آزمایشی)", callback_data="cart:pay:direct"),
    ])

    return text, InlineKeyboardMarkup(kb)

async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    u = db.get_user(user.id)
    if not u:
        db.upsert_user(user.id, (user.full_name or "").strip())
        u = db.get_user(user.id)

    text, markup = build_invoice_text_and_markup(u["id"])
    await update.effective_chat.send_message(text, reply_markup=markup)

async def cb_invoice_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = update.effective_user
    u = db.get_user(user.id)
    text, markup = build_invoice_text_and_markup(u["id"])
    await q.edit_message_text(text, reply_markup=markup)
    await q.answer()

async def cb_cart_inc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pid = int(q.data.split(":")[2])
    user = update.effective_user
    u = db.get_user(user.id)
    # اگر آیتم وجود نداشت، یک‌بار اضافه کن
    p = db.get_product(pid)
    if p:
        oid = db.open_draft_order(u["id"])
        db.add_or_increment_item(oid, pid, float(p["price"]), inc=1)
    text, markup = build_invoice_text_and_markup(u["id"])
    await q.edit_message_text(text, reply_markup=markup)
    await q.answer()

async def cb_cart_dec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pid = int(q.data.split(":")[2])
    user = update.effective_user
    u = db.get_user(user.id)

    # کم کن؛ اگر به صفر رسید حذف می‌شود
    oid = db.open_draft_order(u["id"])
    still = db.change_item_qty(oid, pid, delta=-1)

    text, markup = build_invoice_text_and_markup(u["id"])
    await q.edit_message_text(text, reply_markup=markup)
    await q.answer()

# ---------------------------
# پرداخت‌ها
# ---------------------------
async def cb_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = update.effective_user
    u = db.get_user(user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order or not items:
        await q.answer("سبد خالی است.", show_alert=True)
        return

    total = float(order["total_amount"])
    balance = db.get_balance(u["id"])
    if balance < total:
        await q.answer(
            f"موجودی کافی نیست. موجودی: {toman(balance)} — مبلغ: {toman(total)}",
            show_alert=True,
        )
        return

    # کسر از کیف پول و نهایی‌سازی سفارش
    from psycopg2 import sql as _psql  # برای استفاده داخلی
    with db._conn() as cn, cn.cursor() as cur:  # type: ignore
        # کسر کیف پول
        cur.execute(
            "INSERT INTO wallet_transactions(user_id, kind, amount, meta) "
            "VALUES (%s, 'order', %s, jsonb_build_object('order_id', %s))",
            (u["id"], -total, order["order_id"]),
        )
        # تغییر وضعیت سفارش -> paid (تریگر کش‌بک عمل می‌کند)
        cur.execute(
            "UPDATE orders SET status='paid' WHERE order_id=%s",
            (order["order_id"],),
        )

    await q.answer("پرداخت انجام شد ✅", show_alert=True)
    text, markup = build_invoice_text_and_markup(u["id"])
    await q.edit_message_text(text + "\n\n✅ سفارش پرداخت شد.", reply_markup=markup)

async def cb_pay_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("در نسخهٔ آزمایشی هستیم. به‌زودی درگاه افزوده می‌شود.", show_alert=True)

# ---------------------------
# کیف پول
# ---------------------------
async def msg_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, (user.full_name or "").strip())
    u = db.get_user(user.id)
    bal = db.get_balance(u["id"])
    text = f"موجودی شما: <b>{toman(bal)}</b>\nکش‌بک فعال: {CASHBACK_PERCENT}%"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="wallet:topup")]]
    )
    await update.effective_chat.send_message(text, reply_markup=kb)

async def cb_wallet_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    card = "5029081080984145"
    await q.edit_message_text(
        "برای شارژ، کارت‌به‌کارت کنید و رسید را برای ادمین ارسال کنید.\n"
        f"شماره کارت: <code>{card}</code>"
    )

# ---------------------------
# راهنما/ارتباط/بازی
# ---------------------------
async def msg_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "راهنما:\n"
        f"• {BTN_MENU}: دیدن منو\n"
        f"• {BTN_ORDER}: مدیریت سبد و پرداخت\n"
        f"• {BTN_WALLET}: مشاهده و شارژ کیف پول\n",
        reply_markup=main_keyboard(),
    )

async def msg_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("پیام شما به ادمین ارسال می‌شود. (دمو)")

async def msg_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("...به‌زودی 🎲")

# ---------------------------
# رویدادهای متنی دکمه‌های ReplyKeyboard
# ---------------------------
async def on_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").strip()
    if txt == BTN_MENU:
        await cmd_menu(update, context)
    elif txt == BTN_ORDER:
        await cmd_order(update, context)
    elif txt == BTN_WALLET:
        await msg_wallet(update, context)
    elif txt == BTN_HELP:
        await msg_help(update, context)
    elif txt == BTN_CONTACT:
        await msg_contact(update, context)
    elif txt == BTN_GAME:
        await msg_game(update, context)

# ---------------------------
# خطا
# ---------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await update.effective_chat.send_message("❌ خطای غیرمنتظره. لطفاً دوباره تلاش کن.")
    except Exception:
        pass

# ---------------------------
# ثبت هندلرها
# ---------------------------
def build_handlers():
    return [
        CommandHandler("start", cmd_start),

        # دکمه‌های ReplyKeyboard
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_buttons),

        # منو/محصولات
        CallbackQueryHandler(cb_menu_page, pattern=r"^p:page:\d+$"),
        CallbackQueryHandler(cb_add_product, pattern=r"^p:add:\d+$"),

        # فاکتور و سبد
        CallbackQueryHandler(cb_invoice_view, pattern=r"^inv:view$"),
        CallbackQueryHandler(cb_cart_inc, pattern=r"^cart:inc:\d+$"),
        CallbackQueryHandler(cb_cart_dec, pattern=r"^cart:dec:\d+$"),

        # پرداخت
        CallbackQueryHandler(cb_pay_wallet, pattern=r"^cart:pay:wallet$"),
        CallbackQueryHandler(cb_pay_direct, pattern=r"^cart:pay:direct$"),

        # کیف پول
        CallbackQueryHandler(cb_wallet_topup, pattern=r"^wallet:topup$"),
    ]

def register_error_handler(app):
    app.add_error_handler(on_error)
