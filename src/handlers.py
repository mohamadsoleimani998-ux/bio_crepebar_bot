# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Tuple

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    constants,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from .base import log, ADMIN_IDS
from . import db

# ----------------------------
# تنظیمات محلی این فایل
# ----------------------------
CURRENCY = "تومان"                       # دیگر از base وارد نمی‌کنیم
CARD_NUMBER = "6037-XXXX-XXXX-XXXX"      # شماره کارت شما برای کارت‌به‌کارت

# لیست دسته‌ها (صرفاً برای نمایش – فیلتر دیتابیس اجباری نیست)
CATEGORIES: List[Tuple[str, str]] = [
    ("espresso", "اسپرسو بار گرم و سرد"),
    ("tea", "چای و دمنوش"),
    ("mixhot", "ترکیبی گرم"),
    ("mocktail", "موکتل ها"),
    ("sky", "اسمونی ها"),
    ("cool", "خنک"),
    ("dami", "دمی"),
    ("crepe", "کرپ"),
    ("pancake", "پنکیک"),
    ("diet", "رژیمی ها"),
    ("matcha", "ماچا بار"),
]


# =========================================================
# دستورات پایه
# =========================================================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or "")
    text = (
        "سلام 😊\n"
        "ربات فروشگاهی شما آماده است!\n"
        "از دکمه‌های پایین استفاده کن:"
        "\n• منو 🍭  — دیدن و انتخاب محصول"
        f"\n• سفارش 🧾 — سبد خرید و پرداخت ({CURRENCY})"
        "\n• کیف پول 👛 — نمایش موجودی و شارژ کارت‌به‌کارت"
        "\n• راهنما ℹ️ — توضیحات کوتاه"
    )
    await update.effective_chat.send_message(text)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "راهنما:\n"
        "• از «منو» برای دیدن محصولات استفاده کنید.\n"
        "• داخل «سفارش» می‌توانید آیتم‌ها را کم/زیاد و پرداخت کنید.\n"
        f"• کیف پول قابل شارژ با کارت‌به‌کارت به کارت {CARD_NUMBER} است.\n"
        "بعد از تایید ادمین، موجودی شارژ می‌شود."
    )


# =========================================================
# منو و انتخاب محصول
# =========================================================
def _kb_categories() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title, callback_data=f"CAT:{key}")] for key, title in CATEGORIES]
    return InlineKeyboardMarkup(rows)

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("دستهٔ محصول را انتخاب کنید:", reply_markup=_kb_categories())

async def cb_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]  # الان فقط برای نمایش استفاده می‌شود

    # فعلاً همهٔ محصولات فعال را می‌آوریم (بدون فیلتر دسته)
    page = 1
    prods, total = db.list_products(page=page, page_size=6)
    if not prods:
        await q.edit_message_text("فعلاً محصولی ثبت نشده است. (ادمین می‌تواند محصول اضافه کند)")
        return

    await _show_products_page(q, prods, total, page, key)

async def _show_products_page(q, prods, total, page, cat_key):
    buttons = []
    for p in prods:
        title = f"{p['name']} — {int(p['price']):,} {CURRENCY}".replace(",", "٬")
        buttons.append([InlineKeyboardButton(title, callback_data=f"ADD:{p['id']}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ قبل", callback_data=f"PG:{cat_key}:{page-1}"))
    if page * 6 < total:
        nav.append(InlineKeyboardButton("بعد ▶️", callback_data=f"PG:{cat_key}:{page+1}"))
    if nav:
        buttons.append(nav)

    # دکمهٔ رسیدن به سبد
    buttons.append([InlineKeyboardButton("🧾 مشاهدهٔ فاکتور", callback_data="CART:VIEW")])
    await q.edit_message_text(f"نتایج ({total} مورد):", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_pagination(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, cat_key, page_s = q.data.split(":")
    page = int(page_s)
    prods, total = db.list_products(page=page, page_size=6)
    if not prods:
        await q.edit_message_text("موردی یافت نشد.")
        return
    await _show_products_page(q, prods, total, page, cat_key)

async def cb_add_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":", 1)[1])

    urow = db.get_user(q.from_user.id)
    if not urow:
        await q.edit_message_text("ابتدا /start را بزنید.")
        return

    prow = db.get_product(pid)
    if not prow:
        await q.answer("این محصول موجود نیست.", show_alert=True)
        return

    order_id = db.open_draft_order(urow["id"])
    db.add_or_increment_item(order_id, pid, float(prow["price"]), inc=1)
    await q.answer("به سبد اضافه شد ✅")
    await _show_cart(q, order_id)


# =========================================================
# سبد خرید و پرداخت
# =========================================================
async def cmd_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    urow = db.get_user(update.effective_user.id)
    if not urow:
        await update.effective_chat.send_message("ابتدا /start را بزنید.")
        return
    order, _ = db.get_draft_with_items(urow["id"])
    if not order:
        order_id = db.open_draft_order(urow["id"])
    else:
        order_id = order["order_id"]
    # نمایش فاکتور
    await _send_cart_message(update, order_id)

async def cb_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    urow = db.get_user(q.from_user.id)
    if not urow:
        await q.edit_message_text("ابتدا /start را بزنید.")
        return
    order, _ = db.get_draft_with_items(urow["id"])
    if not order:
        await q.edit_message_text("سبد شما خالی است.")
        return
    await _show_cart(q, order["order_id"])

async def _show_cart(q, order_id: int):
    # helper برای ویرایش پیام فاکتور
    class Dummy:  # تا بتوانیم همان متد ارسال را با ویرایش استفاده کنیم
        async def send(self, text, kb):
            await q.edit_message_text(text, reply_markup=kb)

    await _render_cart(Dummy(), order_id)

async def _send_cart_message(update_or_q, order_id: int):
    class Dummy:
        def __init__(self, chat):
            self.chat = chat
        async def send(self, text, kb):
            await self.chat.send_message(text, reply_markup=kb)

    chat = update_or_q.effective_chat
    await _render_cart(Dummy(chat), order_id)

async def _render_cart(sender, order_id: int):
    # متن و کیبورد فاکتور
    order, items = None, []
    # آیتم‌ها را دوباره از DB بخوانیم (تابع کمکی در db وجود دارد)
    # از get_draft_with_items با user_id کار می‌کند، پس یک بار دیگر از order_id آیتم‌ها را می‌خوانیم:
    # برای سادگی و یکسانی خروجی از get_draft_with_items کمک می‌گیریم:
    # (این تابع هم order را می‌دهد هم آیتم‌ها)
    # اینجا نیاز به user_id داشت؛ راه ساده‌تر این است که همین حالا ساخت متن را از مستقیم جداول انجام ندهیم.
    # پس یک هک کوچک:
    # -- گزینهٔ ساده:
    # متن را از order_items تهیه کنیم:
    from psycopg2.extras import DictCursor
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE order_id=%s", (order_id,))
        order = cur.fetchone()
        cur.execute("""
            SELECT oi.product_id, p.name, oi.qty, oi.unit_price, (oi.qty*oi.unit_price) AS line_total
              FROM order_items oi
              JOIN products p ON p.product_id = oi.product_id
             WHERE oi.order_id=%s
             ORDER BY oi.item_id
        """, (order_id,))
        items = cur.fetchall()

    lines = [f"🧾 فاکتور #{order_id}", ""]
    if not items:
        lines.append("سبد شما خالی است.")
    else:
        for it in items:
            lines.append(f"• {it['name']} × {it['qty']} = {int(it['line_total']):,} {CURRENCY}".replace(",", "٬"))

    total = int(order["total_amount"])
    lines.append("")
    lines.append(f"مبلغ کل: {total:,} {CURRENCY}".replace(",", "٬"))

    kb_rows = []
    # ردیف کم/زیاد برای هر آیتم
    for it in items:
        kb_rows.append([
            InlineKeyboardButton(f"➖ {it['name']}", callback_data=f"QTY:-:{order_id}:{it['product_id']}"),
            InlineKeyboardButton(f"➕ {it['name']}", callback_data=f"QTY:+:{order_id}:{it['product_id']}"),
        ])

    kb_rows.append([InlineKeyboardButton("🗑 خالی کردن سبد", callback_data=f"CLEAR:{order_id}")])

    # پرداخت
    kb_rows.append([
        InlineKeyboardButton("💳 پرداخت با کیف پول", callback_data=f"PAY:WALLET:{order_id}"),
        InlineKeyboardButton("🧾 پرداخت کارت‌به‌کارت", callback_data=f"PAY:CARD:{order_id}:{total}"),
    ])

    await sender.send("\n".join(lines), InlineKeyboardMarkup(kb_rows))

async def cb_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, sign, order_s, prod_s = q.data.split(":")
    order_id = int(order_s)
    product_id = int(prod_s)
    delta = 1 if sign == "+" else -1
    still = db.change_item_qty(order_id, product_id, delta)
    if not still:
        # آیتم حذف شد یا نبود
        pass
    await _show_cart(q, order_id)

async def cb_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = int(q.data.split(":")[1])
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))
    await _show_cart(q, order_id)

async def cb_pay_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, _, order_s = q.data.split(":")
    order_id = int(order_s)
    # اطلاعات کاربر و سفارش
    from psycopg2.extras import DictCursor
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT user_id, total_amount FROM orders WHERE order_id=%s", (order_id,))
        row = cur.fetchone()
        if not row:
            await q.edit_message_text("سفارش پیدا نشد.")
            return
        user_id = row["user_id"]
        total = float(row["total_amount"])
        balance = db.get_balance(user_id)

        if balance < total:
            need = int(total - balance)
            await q.edit_message_text(
                f"موجودی کافی نیست. کمبود: {need:,} {CURRENCY}".replace(",", "٬")
            )
            return

        # کسر از کیف پول
        cur.execute("""
            INSERT INTO wallet_transactions(user_id, kind, amount, meta)
            VALUES (%s, 'order', %s, jsonb_build_object('order_id', %s))
        """, (user_id, -total, order_id))
        # ثبت پرداخت
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order_id,))

    await q.edit_message_text("پرداخت با کیف پول با موفقیت انجام شد ✅")


async def cb_pay_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, _, order_s, total_s = q.data.split(":")
    order_id = int(order_s)
    total = int(total_s)
    uid = update.effective_user.id

    ctx.user_data["await_card_receipt"] = {"order_id": order_id, "total": total}
    txt = (
        f"مبلغ {total:,} {CURRENCY}".replace(",", "٬")
        + f" را به کارت زیر واریز کنید:\n\n{CARD_NUMBER}\n\n"
          "سپس عکس رسید را با کپشن «پرداخت انجام شد» ارسال کنید.\n"
          "پس از تایید ادمین، سفارش شما «پرداخت‌شده» می‌شود."
    )
    await q.edit_message_text(txt)

async def on_photo_for_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # دریافت رسید برای سفارش
    pending = ctx.user_data.get("await_card_receipt")
    if not pending:
        return
    del ctx.user_data["await_card_receipt"]

    order_id = pending["order_id"]
    total = pending["total"]
    uid = update.effective_user.id

    # ارسال برای ادمین‌ها جهت تایید
    caption = (
        f"🧾 درخواست تایید پرداخت کارت‌به‌کارت\n"
        f"کاربر: {uid}\n"
        f"سفارش #{order_id}\n"
        f"مبلغ: {total:,} {CURRENCY}".replace(",", "٬")
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"ADMIN:CONFIRM_ORDER:{uid}:{order_id}:{total}")]]
    )
    photo = update.message.photo[-1].file_id
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_photo(admin_id, photo=photo, caption=caption, reply_markup=kb)
        except Exception as e:
            log.error(f"send admin photo failed: {e}")

    await update.effective_chat.send_message("رسید ارسال شد. منتظر تایید ادمین بمانید.")

async def admin_confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, _, uid_s, order_s, total_s = q.data.split(":")
    uid = int(uid_s)
    order_id = int(order_s)
    total = int(total_s)

    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order_id,))

    await q.edit_message_caption((q.message.caption or "") + "\n\n✔️ سفارش پرداخت‌شده علامت خورد.")
    try:
        await ctx.bot.send_message(uid, "پرداخت شما تایید شد. سفارش به وضعیت «پرداخت‌شده» تغییر یافت ✅")
    except Exception:
        pass


# =========================================================
# کیف پول: نمایش و شارژ کارت‌به‌کارت
# =========================================================
async def cmd_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    urow = db.get_user(update.effective_user.id)
    if not urow:
        await update.effective_chat.send_message("ابتدا /start را بزنید.")
        return
    bal = int(db.get_balance(urow["id"]))
    from psycopg2.extras import DictCursor
    with db._conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent'")
        row = cur.fetchone()
        cb = row["value"] if row else "0"

    text = f"موجودی شما: {bal:,} {CURRENCY}\nکش‌بک فعال: %{cb}".replace(",", "٬")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="TOPUP:ASK")]]
    )
    await update.effective_chat.send_message(text, reply_markup=kb)

async def cb_topup_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["await_topup"] = True
    text = (
        "برای شارژ کیف پول:\n"
        f"۱) مبلغ دلخواه را به کارت {CARD_NUMBER} واریز کنید.\n"
        "۲) سپس عکس رسید را با *کپشن عددی مبلغ* بفرستید (مثلاً: 150000).\n"
        "ادمین تایید کند، موجودی شما شارژ می‌شود."
    )
    await q.edit_message_text(text, parse_mode=constants.ParseMode.MARKDOWN)

async def on_photo_for_topup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("await_topup"):
        return
    del ctx.user_data["await_topup"]

    caption = (update.message.caption or "").strip()
    try:
        amount = int("".join(ch for ch in caption if ch.isdigit()))
    except Exception:
        amount = 0

    if amount <= 0:
        await update.effective_chat.send_message("مبلغ در کپشن یافت نشد. لطفاً دوباره تلاش کنید و فقط عدد بنویسید.")
        return

    uid = update.effective_user.id
    user = db.get_user(uid)
    if not user:
        await update.effective_chat.send_message("ابتدا /start را بزنید.")
        return

    # برای ادمین بفرست
    cap = (
        f"درخواست شارژ کیف پول\n"
        f"کاربر: {uid}\n"
        f"مبلغ: {amount:,} {CURRENCY}".replace(",", "٬")
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ تایید و شارژ", callback_data=f"ADMIN:TOPUP_OK:{user['id']}:{amount}")]]
    )
    photo = update.message.photo[-1].file_id
    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_photo(admin_id, photo=photo, caption=cap, reply_markup=kb)
        except Exception as e:
            log.error(f"send admin topup failed: {e}")

    await update.effective_chat.send_message("رسید ارسال شد. بعد از تایید ادمین، کیف پول شارژ می‌شود.")

async def admin_topup_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, _, user_id_s, amount_s = q.data.split(":")
    user_id = int(user_id_s)
    amount = int(amount_s)
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO wallet_transactions(user_id, kind, amount, meta)
            VALUES (%s, 'topup', %s, jsonb_build_object('by', 'admin'))
        """, (user_id, amount))
    await q.edit_message_caption((q.message.caption or "") + "\n\n✔️ شارژ انجام شد.")
    # اطلاع به کاربر
    try:
        with db._conn() as cn, cn.cursor() as cur:
            cur.execute("SELECT telegram_id FROM users WHERE user_id=%s", (user_id,))
            tg_id = cur.fetchone()[0]
        await ctx.bot.send_message(tg_id, f"✅ کیف پول شما به مقدار {amount:,} {CURRENCY} شارژ شد.".replace(",", "٬"))
    except Exception:
        pass


# =========================================================
# افزودن محصول توسط ادمین (ساده)
# /addproduct نام | قیمت
# =========================================================
async def cmd_addproduct(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    args = (update.message.text or "").split(" ", 1)
    if len(args) < 2 or "|" not in args[1]:
        await update.effective_chat.send_message("فرمت: /addproduct نام | قیمت\nمثال: /addproduct اسپرسو دوبل | 80000")
        return
    name, price_s = [x.strip() for x in args[1].split("|", 1)]
    try:
        price = float(price_s.replace(",", ""))
    except Exception:
        await update.effective_chat.send_message("قیمت نامعتبر است.")
        return

    with db._conn() as cn, cn.cursor() as cur:
        cur.execute(
            "INSERT INTO products(name, price, is_active) VALUES (%s,%s,TRUE)",
            (name, price),
        )
    await update.effective_chat.send_message("محصول اضافه شد ✅")


# =========================================================
# ثبت هندلرها
# =========================================================
def build_handlers():
    return [
        CommandHandler("start", cmd_start),
        CommandHandler("help", cmd_help),
        CommandHandler("menu", cmd_menu),
        CommandHandler("order", cmd_order),
        CommandHandler("wallet", cmd_wallet),

        # ادمین
        CommandHandler("addproduct", cmd_addproduct),

        # کال‌بک‌ها
        CallbackQueryHandler(cb_category, pattern=r"^CAT:"),
        CallbackQueryHandler(cb_pagination, pattern=r"^PG:"),
        CallbackQueryHandler(cb_add_product, pattern=r"^ADD:\d+$"),
        CallbackQueryHandler(cb_cart, pattern=r"^CART:VIEW$"),
        CallbackQueryHandler(cb_qty, pattern=r"^QTY:"),
        CallbackQueryHandler(cb_clear, pattern=r"^CLEAR:\d+$"),
        CallbackQueryHandler(cb_pay_wallet, pattern=r"^PAY:WALLET:\d+$"),
        CallbackQueryHandler(cb_pay_card, pattern=r"^PAY:CARD:\d+:\d+$"),
        CallbackQueryHandler(admin_confirm_order, pattern=r"^ADMIN:CONFIRM_ORDER:"),
        CallbackQueryHandler(cb_topup_ask, pattern=r"^TOPUP:ASK$"),
        CallbackQueryHandler(admin_topup_ok, pattern=r"^ADMIN:TOPUP_OK:"),

        # عکس رسیدها
        MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo_for_topup),
        MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo_for_card),
    ]
