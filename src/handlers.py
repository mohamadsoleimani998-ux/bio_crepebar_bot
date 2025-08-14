# -*- coding: utf-8 -*-
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
from .base import (
    log, fmt_money, is_admin, ADMIN_IDS,
    CARD_PAN, CARD_NAME, CARD_NOTE, CURRENCY
)
from . import db

# ===================== Keyboards =====================
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

def products_keyboard(cat_id: int, page: int, total: int, page_size: int = 6):
    # ناوبری
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"catp:{cat_id}:{page-1}"))
    if page * page_size < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"catp:{cat_id}:{page+1}"))

    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("➕ افزودن محصول (ادمین)", callback_data=f"addp:{cat_id}")])
    rows.append([InlineKeyboardButton("🧺 رفتن به سبد", callback_data="cart:open")])
    return InlineKeyboardMarkup(rows)

def cart_keyboard(order_id: int, shipping: str | None, pay: str | None, can_submit: bool):
    sh = shipping or "انتخاب نشده"
    py = pay or "انتخاب نشده"
    rows = [
        [InlineKeyboardButton(f"روش ارسال: {sh}", callback_data=f"ship:toggle")],
        [InlineKeyboardButton(f"روش پرداخت: {py}", callback_data=f"pay:toggle")],
    ]
    if can_submit:
        rows.append([InlineKeyboardButton("ثبت نهایی ✅", callback_data=f"submit:{order_id}")])
    rows.append([InlineKeyboardButton("خالی کردن 🧹", callback_data=f"empty:{order_id}")])
    return InlineKeyboardMarkup(rows)

def pay_keyboard(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("پرداخت از کیف پول 👛", callback_data=f"payw:{order_id}")],
        [InlineKeyboardButton("کارت‌به‌کارت 🧾", callback_data=f"payc:{order_id}")],
    ])

# ===================== Conversations (Add Product & Topup) =====================
(AP_NAME, AP_PRICE, AP_DESC, AP_PHOTO, TOPUP_AMOUNT, TOPUP_WAIT_RECEIPT) = range(6)

# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or "")
    await update.effective_chat.send_message(
        "سلام 😊\nبه ربات فروشگاهی بیو کِرِپ‌بار خوش آمدید!",
        reply_markup=main_keyboard()
    )

# ---------- Menu ----------
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("دستهٔ محصول را انتخاب کنید:", reply_markup=categories_keyboard())

# ---------- Category & Paging ----------
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

    if not items:
        txt = "در این دسته هنوز محصولی ثبت نشده است."
    else:
        lines = [f"🧺 محصولات (صفحه {page})\n\nبرای افزودن، روی دکمه‌ی هر محصول بزنید:"]
        for p in items:
            price = fmt_money(p["price"])
            # یک ردیف دکمه برای افزودن هر محصول
            lines.append(f"• {p['name']} — {price}")
        txt = "\n".join(lines)

    # زیر متن، دکمه‌های «افزودن» را هم می‌گذاریم
    # هر دکمه‌ی افزودن به سبد، در یک ردیف جدا
    kb_rows = []
    for p in items:
        kb_rows.append([InlineKeyboardButton(f"➕ {p['name']}", callback_data=f"add:{p['id']}")])
    # ناوبری + سایر
    nav_keyboard = products_keyboard(cat_id, page, total, page_size)
    kb_rows.extend(nav_keyboard.inline_keyboard)
    kb = InlineKeyboardMarkup(kb_rows)

    if update.callback_query:
        await update.effective_message.edit_text(txt, reply_markup=kb)
    else:
        await update.effective_chat.send_message(txt, reply_markup=kb)

# ---------- Add to cart ----------
async def cb_add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, pid = q.data.split(":")
    pid = int(pid)
    prod = db.get_product(pid)
    if not prod:
        return await q.answer("محصول یافت نشد.", show_alert=True)
    u = db.get_user_by_tg(update.effective_user.id)
    oid = db.open_draft_order(u["id"])
    db.add_or_increment_item(oid, pid, float(prod["price"]), 1)
    await q.answer("به سبد افزوده شد ✅", show_alert=False)

# ---------- Cart (Order tab) ----------
async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order or not items:
        return await update.effective_chat.send_message("سبد شما خالی است.", reply_markup=main_keyboard())

    total = order["total_amount"]
    # گزینه‌های انتخابی (در جدول orders ذخیره می‌کنیم)
    shipping = order.get("shipping_method")
    pay = order.get("payment_method")

    lines = ["🧾 سبد خرید:\n"]
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} — {fmt_money(it['line_total'])}")
    lines.append(f"\nجمع کل: {fmt_money(total)}")
    lines.append("\nروش ارسال را تغییر دهید و سپس روش پرداخت را انتخاب کنید:")
    await update.effective_chat.send_message(
        "\n".join(lines),
        reply_markup=cart_keyboard(order["order_id"], shipping, pay, can_submit=bool(shipping and pay))
    )

# تغییر روش ارسال (حضوری/پیک)
async def cb_toggle_shipping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order: return await q.answer("سبد خالی است.", show_alert=True)
    shipping = order.get("shipping_method") or ""
    new_v = "پیک" if shipping != "پیک" else "حضوری"
    db.set_order_option(order["order_id"], "shipping_method", new_v)
    # بازنمایش
    await order_entry(update, context)

# تغییر روش پرداخت (کیف/کارت)
async def cb_toggle_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not order: return await q.answer("سبد خالی است.", show_alert=True)
    pay = order.get("payment_method") or ""
    new_v = "wallet" if pay != "wallet" else "card"
    db.set_order_option(order["order_id"], "payment_method", new_v)
    await order_entry(update, context)

# ثبت نهایی: بر اساس روش پرداخت
async def cb_submit_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    oid = int(oid)

    order, items = db.get_order_with_items_by_id(oid)
    if not order or not items:
        return await q.edit_message_text("سبد خالی است.")
    pay = order.get("payment_method")
    shipping = order.get("shipping_method")
    if not (pay and shipping):
        return await q.answer("روش ارسال/پرداخت را انتخاب کنید.", show_alert=True)

    u = db.get_user_by_tg(update.effective_user.id)

    if pay == "wallet":
        bal = db.get_balance(u["id"])
        if bal < float(order["total_amount"]):
            return await q.edit_message_text(
                f"❗️ موجودی کیف پول کافی نیست.\nموجودی: {fmt_money(bal)}\nجمع کل: {fmt_money(order['total_amount'])}\nاز «👛 کیف پول» شارژ کنید."
            )
        # کسر و پرداخت
        db.add_wallet_tx(u["id"], "order", -float(order["total_amount"]), {"order_id": oid})
        db.mark_order_paid(oid)
        await q.edit_message_text("✅ سفارش با کیف پول پرداخت شد. ممنونیم!")
        # اطلاع به ادمین
        await _notify_admins(context, f"🛒 سفارش جدید پرداخت شد (کیف پول)\nOrder #{oid}\nکاربر: {u['name']} ({u['telegram_id']})\nمبلغ: {fmt_money(order['total_amount'])}\nروش ارسال: {shipping}")
        return

    # pay == "card" → کارت‌به‌کارت
    txt = (
        "✅ سفارش ثبت شد و منتظر پرداخت است.\n"
        "لطفاً مبلغ سفارش را کارت‌به‌کارت کنید و **رسید** را به همین چت ارسال کنید.\n\n"
        f"• کارت: {CARD_PAN}\n• به نام: {CARD_NAME}\n{CARD_NOTE}\n\n"
        "پس از ارسال رسید، ادمین تایید می‌کند و وضعیت سفارش «پرداخت‌شده» می‌شود."
    )
    await q.edit_message_text(txt)
    # برای ادمین هم یک درخواست تایید می‌سازیم
    req_id = db.create_order_pay_request(oid, u["id"], float(order["total_amount"]))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید پرداخت سفارش ✅", callback_data=f"opa:{req_id}")],
        [InlineKeyboardButton("رد ❌", callback_data=f"opr:{req_id}")],
    ])
    await _notify_admins(context,
        f"🔔 سفارش منتظر تایید پرداخت (کارت‌به‌کارت)\nOrder #{oid}\nکاربر: {u['name']} ({u['telegram_id']})\nمبلغ: {fmt_money(order['total_amount'])}\nروش ارسال: {shipping}",
        reply_markup=kb
    )

# خالی کردن سبد
async def cb_empty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, oid = q.data.split(":")
    db.empty_order(int(oid))
    await q.edit_message_text("سبد خالی شد.")

# ---------- Add product (admin only) ----------
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
    await update.message.reply_text("قیمت محصول را به تومان بفرستید (مثلاً 85000):")
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
    await show_category(update, context, ap["cat_id"], 1)
    return ConversationHandler.END

# ---------- Wallet ----------
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
    await update.message.reply_text("✅ مبلغ دریافت شد. حالا **عکس رسید** را ارسال کنید.")
    return TOPUP_WAIT_RECEIPT

async def topup_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return await update.message.reply_text("لطفاً عکس رسید را بفرستید.")
    u = db.get_user_by_tg(update.effective_user.id)
    amount = context.user_data.get("topup_amount", 0)
    req_id = db.create_topup_request(u["id"], amount, update.message.message_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید شارژ ✅", callback_data=f"tpa:{req_id}")],
        [InlineKeyboardButton("رد ❌",   callback_data=f"tpr:{req_id}")],
    ])

    # ارسال به همه ادمین‌ها (با try/except)
    sent_any = False
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=update.message.photo[-1].file_id,
                caption=f"🔔 درخواست شارژ کیف پول\nکاربر: {u['name']} ({u['telegram_id']})\nمبلغ: {fmt_money(amount)}\nreq_id={req_id}",
                reply_markup=kb
            )
            sent_any = True
        except Exception as e:
            log.warning(f"send to admin failed: {e}")
    if not sent_any:
        log.warning("No admin notified: ADMIN_IDS empty?")

    await update.message.reply_text("✅ درخواست شارژ ارسال شد. پس از تایید ادمین، کیف پول شما شارژ می‌شود.")
    return ConversationHandler.END

# تایید/رد شارژ یا پرداخت سفارش توسط ادمین
async def cb_topup_or_order_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data
    approve = data.startswith("tpa:") or data.startswith("opa:")
    req_id = int(data.split(":")[1])
    row = db.decide_payment(req_id, approve)
    if not row:
        return await q.edit_message_caption(caption="درخواست یافت نشد یا قبلاً بررسی شده.")
    user_id, amount, order_id = int(row["user_id"]), float(row["amount"]), row.get("order_id")
    # اگر مربوط به سفارش بود:
    if order_id and approve:
        db.mark_order_paid(order_id)
        await q.edit_message_caption(caption=f"✅ پرداخت سفارش #{order_id} تایید شد.")
    elif order_id and not approve:
        await q.edit_message_caption(caption=f"❌ پرداخت سفارش #{order_id} رد شد.")
    else:
        # شارژ کیف پول
        if approve:
            db.add_wallet_tx(user_id, "topup", amount, {"req_id": req_id})
            await q.edit_message_caption(caption=f"✅ شارژ تایید شد و {fmt_money(amount)} اضافه گردید.")
        else:
            await q.edit_message_caption(caption=f"❌ شارژ رد شد.")

    # اطلاع به کاربر
    tg_id = db.get_user_tg_by_id(user_id)
    if order_id:
        if approve:
            await context.bot.send_message(tg_id, f"✅ پرداخت سفارش #{order_id} تایید شد. سپاس!")
        else:
            await context.bot.send_message(tg_id, f"❌ پرداخت سفارش #{order_id} رد شد.")
    else:
        if approve:
            await context.bot.send_message(tg_id, f"✅ شارژ {fmt_money(amount)} تایید شد و به کیف پول اضافه گردید.")
        else:
            await context.bot.send_message(tg_id, f"❌ درخواست شارژ شما رد شد.")

# ---------- Help ----------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "راهنما:\n"
        "• از «🍭 منو» دسته‌ها را ببینید و با دکمه‌ی هر محصول به سبد اضافه کنید.\n"
        "• از «🧾 سفارش» روش ارسال/پرداخت را انتخاب و ثبت نهایی کنید.\n"
        "• از «👛 کیف پول» با کارت‌به‌کارت شارژ کنید (رسید را بفرستید تا ادمین تایید کند).\n"
        "• پرداخت‌ها: کیف‌پول یا کارت‌به‌کارت. کش‌بک پس از پرداخت موفق اعمال می‌شود.",
        reply_markup=main_keyboard()
    )

# ---------- Internal ----------
async def _notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    ok = False
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=reply_markup)
            ok = True
        except Exception as e:
            log.warning(f"notify admin failed: {e}")
    if not ok:
        log.warning("no admin notified")

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
        CallbackQueryHandler(cb_add_to_cart,   pattern=r"^add:\d+$"),

        CallbackQueryHandler(cb_toggle_shipping, pattern=r"^ship:toggle$"),
        CallbackQueryHandler(cb_toggle_pay,      pattern=r"^pay:toggle$"),
        CallbackQueryHandler(cb_submit_order,    pattern=r"^submit:\d+$"),
        CallbackQueryHandler(cb_empty,           pattern=r"^empty:\d+$"),

        # تایید/رد: tpa|tpr برای شارژ، opa|opr برای سفارش
        CallbackQueryHandler(cb_topup_or_order_decide, pattern=r"^(tpa|tpr|opa|opr):\d+$"),

        conv_add_product,
        conv_topup,
    ]
