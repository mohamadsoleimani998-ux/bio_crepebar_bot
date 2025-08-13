# src/handlers.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    Handler,
)

from .base import ADMIN_IDS, log
from . import db

# ==============================
# ثابت‌ها (متن فارسی دکمه‌ها)
# ==============================
BTN_MENU      = "منو 🍭"
BTN_ORDER     = "سفارش 🧾"
BTN_WALLET    = "کیف پول 👛"
BTN_HELP      = "راهنما ℹ️"
BTN_CONTACT   = "ارتباط با ما ☎️"

BTN_VIEW_INVOICE = "مشاهده فاکتور 🧾"
BTN_PAY_WALLET   = "پرداخت از کیف پول 👛"
BTN_PAY_CASH     = "پرداخت مستقیم 💳"   # (کارت‌به‌کارت/حضوری)
BTN_BACK_MENU    = "بازگشت به منو ◀️"

# callback prefixes
CB_PROD   = "prod:"     # prod:<id>
CB_PAGE   = "page:"     # page:<page>
CB_INC    = "inc:"      # inc:<product_id>
CB_DEC    = "dec:"      # dec:<product_id>
CB_REM    = "rem:"      # rem:<product_id>
CB_INV    = "invoice"   # invoice
CB_PAY_W  = "pay:wallet"
CB_PAY_C  = "pay:cash"

PAGE_SIZE = 6

# ==============================
# کیبورد Reply اصلی
# ==============================
def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_MENU), KeyboardButton(BTN_ORDER)],
        [KeyboardButton(BTN_WALLET), KeyboardButton("بازی 🎮")],
        [KeyboardButton(BTN_CONTACT), KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ==============================
# ابزارهای نمایشی
# ==============================
def fmt_price(n: float) -> str:
    try:
        n = float(n)
    except Exception:
        return str(n)
    s = f"{int(n):,}".replace(",", "،")
    return f"{s} تومان"

def product_list_kb(page: int, products: List[dict], total: int) -> InlineKeyboardMarkup:
    btns: List[List[InlineKeyboardButton]] = []

    for p in products:
        title = f"{fmt_price(p['price'])} — {p['name']}"
        btns.append([InlineKeyboardButton(title, callback_data=f"{CB_PROD}{p['id']}")])

    # نوار صفحه‌بندی
    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pager = [InlineKeyboardButton(f"{page}/{max_page}", callback_data="noop")]
    if page > 1:
        pager.insert(0, InlineKeyboardButton("◀️", callback_data=f"{CB_PAGE}{page-1}"))
    if page < max_page:
        pager.append(InlineKeyboardButton("▶️", callback_data=f"{CB_PAGE}{page+1}"))
    btns.append(pager)

    btns.append([InlineKeyboardButton(BTN_VIEW_INVOICE, callback_data=CB_INV)])
    return InlineKeyboardMarkup(btns)

def invoice_kb(items_exist: bool) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if items_exist:
        rows.append([InlineKeyboardButton(BTN_PAY_WALLET, callback_data=CB_PAY_W)])
        rows.append([InlineKeyboardButton(BTN_PAY_CASH,   callback_data=CB_PAY_C)])
    rows.append([InlineKeyboardButton("ادامه خرید از منو 🍭", callback_data=f"{CB_PAGE}1")])
    return InlineKeyboardMarkup(rows)

def order_items_kb(items: List[dict]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for it in items:
        name = it["name"]
        qty  = it["qty"]
        pid  = it["product_id"]
        rows.append([
            InlineKeyboardButton(f"➖", callback_data=f"{CB_DEC}{pid}"),
            InlineKeyboardButton(f"{name} × {qty}", callback_data="noop"),
            InlineKeyboardButton(f"➕", callback_data=f"{CB_INC}{pid}"),
            InlineKeyboardButton(f"🗑", callback_data=f"{CB_REM}{pid}"),
        ])
    rows.append([InlineKeyboardButton(BTN_PAY_WALLET, callback_data=CB_PAY_W)])
    rows.append([InlineKeyboardButton(BTN_PAY_CASH,   callback_data=CB_PAY_C)])
    rows.append([InlineKeyboardButton("ادامه خرید از منو 🍭", callback_data=f"{CB_PAGE}1")])
    return InlineKeyboardMarkup(rows)

# ==============================
# ورود/ثبت نام ساده
# ==============================
async def ensure_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    tg = update.effective_user
    db.upsert_user(tg.id, (tg.full_name or "").strip())
    u = db.get_user(tg.id)
    return int(u["id"])

# ==============================
# /start
# ==============================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, ctx)
    text = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        f"• {BTN_MENU}: نمایش محصولات\n"
        f"• {BTN_ORDER}: ثبت سفارش و فاکتور\n"
        f"• {BTN_WALLET}: مشاهده/شارژ کیف‌پول و کش‌بک ۳٪ بعد هر خرید\n"
        f"• {BTN_HELP}: راهنما"
    )
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())

# ==============================
# منو (نمایش محصولات با دکمه اینلاین)
# ==============================
async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 1):
    uid = await ensure_user(update, ctx)
    products, total = db.list_products(page=page, page_size=PAGE_SIZE)
    if not products:
        await update.effective_message.reply_text("هنوز محصول فعالی ثبت نشده.", reply_markup=main_keyboard())
        return
    await update.effective_message.reply_text(
        "منو:",
        reply_markup=product_list_kb(page, products, total),
    )

# ==============================
# سفارش/فاکتور
# ==============================
def _format_invoice(order: dict, items: List[dict]) -> str:
    if not order or not items:
        return "سبد خرید خالی است."
    lines = ["فاکتور موقت:\n"]
    total = 0
    for it in items:
        lt = float(it["line_total"])
        total += lt
        lines.append(f"• {it['name']} × {it['qty']} = {fmt_price(lt)}")
    lines.append(f"\nجمع کل: {fmt_price(total)}")
    return "\n".join(lines)

async def show_invoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await ensure_user(update, ctx)
    order, items = db.get_draft_with_items(uid)
    if not order or not items:
        await update.effective_message.reply_text("سبد خرید خالی است.", reply_markup=main_keyboard())
        return
    text = _format_invoice(order, items)
    await update.effective_message.reply_text(text, reply_markup=order_items_kb(items))

# ==============================
# کیف پول
# ==============================
async def show_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await ensure_user(update, ctx)
    bal = db.get_balance(uid)
    txt = f"موجودی شما: {fmt_price(bal)}\nکش‌بک فعال: %3"
    kb = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="topup")
    )
    await update.effective_message.reply_text(txt, reply_markup=kb)

# ==============================
# Callback ها
# ==============================
async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    await q.answer()

    # صفحه‌بندی منو
    if data.startswith(CB_PAGE):
        page = int(data.split(":")[1])
        products, total = db.list_products(page=page, page_size=PAGE_SIZE)
        await q.edit_message_reply_markup(reply_markup=product_list_kb(page, products, total))
        return

    # انتخاب محصول از منو
    if data.startswith(CB_PROD):
        pid = int(data.split(":")[1])
        uid = await ensure_user(update, ctx)
        order_id = db.open_draft_order(uid)
        p = db.get_product(pid)
        if not p:
            await q.edit_message_text("این محصول در دسترس نیست.")
            return
        db.add_or_increment_item(order_id, pid, float(p["price"]), inc=1)
        await q.answer("به سبد اضافه شد ✅", show_alert=False)
        # فاکتورِ خلاصه
        order, items = db.get_draft_with_items(uid)
        await q.message.reply_text(_format_invoice(order, items), reply_markup=order_items_kb(items))
        return

    # افزایش/کاهش/حذف از فاکتور
    if data.startswith(CB_INC) or data.startswith(CB_DEC) or data.startswith(CB_REM):
        uid = await ensure_user(update, ctx)
        order_id = db.open_draft_order(uid)
        pid = int(data.split(":")[1])

        if data.startswith(CB_INC):
            p = db.get_product(pid)
            if p:
                db.add_or_increment_item(order_id, pid, float(p["price"]), inc=1)
        elif data.startswith(CB_DEC):
            db.change_item_qty(order_id, pid, delta=-1)
        else:  # REM
            db.remove_item(order_id, pid)

        order, items = db.get_draft_with_items(uid)
        # آپدیت پیام فاکتور (اگر ساختارش فرق داشت، پیام جدید بفرست)
        try:
            await q.edit_message_text(_format_invoice(order, items), reply_markup=order_items_kb(items))
        except Exception:
            await q.message.reply_text(_format_invoice(order, items), reply_markup=order_items_kb(items))
        return

    # نمایش فاکتور از منو
    if data == CB_INV:
        await show_invoice(update, ctx)
        return

    # پرداخت
    if data == CB_PAY_W:
        await pay_with_wallet(update, ctx)
        return

    if data == CB_PAY_C:
        await mark_direct_payment(update, ctx)
        return

    # شارژ
    if data == "topup":
        await q.message.reply_text(
            "برای شارژ کارت‌به‌کارت، مبلغ دلخواه را به کارت زیر واریز کنید و رسید را برای ادمین ارسال کنید:\n"
            "شماره کارت: 5029-0810-8098-4145\n"
            "پس از تایید، مبلغ به کیف‌پول شما افزوده می‌شود."
        )
        return

# ==============================
# پرداخت‌ها
# ==============================
async def pay_with_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await ensure_user(update, ctx)
    order, items = db.get_draft_with_items(uid)
    if not order or not items:
        await update.effective_message.reply_text("سبد خرید خالی است.")
        return

    total = float(order["total_amount"])
    bal = db.get_balance(uid)
    if bal < total:
        need = total - bal
        await update.effective_message.reply_text(
            f"موجودی کافی نیست. {fmt_price(need)} دیگر لازم دارید.",
            reply_markup=invoice_kb(True),
        )
        return

    # کسر از کیف و ثبت پرداخت
    # از اتصال db استفاده می‌کنیم
    with db._conn() as cn, cn.cursor() as cur:  # type: ignore
        # 1) کسر از کیف (ثبت تراکنش منفی)
        cur.execute(
            "INSERT INTO wallet_transactions(user_id, kind, amount, meta) "
            "VALUES (%s,'order', %s, jsonb_build_object('order_id', %s))",
            (uid, -total, int(order["order_id"])),
        )
        # 2) تغییر وضعیت سفارش
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (int(order["order_id"]),))

    await update.effective_message.reply_text(
        "پرداخت با موفقیت انجام شد ✅\nکش‌بک تا چند لحظه دیگر به کیف شما افزوده می‌شود.",
        reply_markup=main_keyboard()
    )

async def mark_direct_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await ensure_user(update, ctx)
    order, items = db.get_draft_with_items(uid)
    if not order or not items:
        await update.effective_message.reply_text("سبد خرید خالی است.")
        return

    with db._conn() as cn, cn.cursor() as cur:  # type: ignore
        cur.execute("UPDATE orders SET status='submitted' WHERE order_id=%s", (int(order["order_id"]),))

    await update.effective_message.reply_text(
        "سفارش ثبت شد. برای پرداخت مستقیم (کارت‌به‌کارت) لطفاً رسید را برای ادمین ارسال کنید.\n"
        "پس از تایید، وضعیت به *paid* تغییر می‌کند.",
        reply_markup=main_keyboard()
    )

# ==============================
# مسیج‌هندهرهای متنی
# ==============================
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").strip()
    if txt == BTN_MENU:
        await show_menu(update, ctx, page=1)
    elif txt == BTN_ORDER or txt == BTN_VIEW_INVOICE:
        await show_invoice(update, ctx)
    elif txt == BTN_WALLET:
        await show_wallet(update, ctx)
    elif txt == BTN_HELP:
        await update.effective_message.reply_text(
            "راهنما:\n"
            "از «منو» محصول انتخاب کن و به سبد اضافه کن. سپس «مشاهده فاکتور» را بزن و پرداخت را انجام بده."
        )
    else:
        await update.effective_message.reply_text("از دکمه‌های پایین استفاده کن 🙏", reply_markup=main_keyboard())

# ==============================
# Build handlers
# ==============================
def build_handlers() -> List[Handler]:
    return [
        CommandHandler("start", cmd_start),
        # متنی
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
        # کال‌بک‌ها
        CallbackQueryHandler(cb_router),
    ]
