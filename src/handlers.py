# src/handlers.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, List, Tuple, Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Message, InputMediaPhoto
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackContext, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)

from .base import log, ADMIN_IDS, CURRENCY
from . import db

# -----------------------------
# دسته‌بندی‌های درخواستی
# -----------------------------
CATEGORIES: Final[List[str]] = [
    "اسپرسو بار گرم و سرد",
    "چای و دمنوش",
    "ترکیبی گرم",
    "موکتل ها",
    "اسمونی ها",
    "خنک",
    "دمی",
    "کرپ",
    "پنکیک",
    "رژیمی ها",
    "ماچا بار",
]

# =============================
# ابزارک‌های کمکی
# =============================
def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(int(i) for i in ADMIN_IDS)
    except Exception:
        return False

def money(n: float | int) -> str:
    return f"{int(n):,} {CURRENCY}"

def kb(rows: List[List[Tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])

# =============================
# /start و منوی اصلی
# =============================
async def cmd_start(update: Update, context: CallbackContext) -> None:
    u = update.effective_user
    if u:
        db.upsert_user(u.id, u.full_name)

    txt = (
        "سلام 😊\n"
        "• منو: نمایش و سفارش محصولات\n"
        "• کیف پول: موجودی/شارژ کارت‌به‌کارت\n"
        "• راهنما: دستورها\n"
    )
    rows = [
        [("🍭 منو", "menu:root"), ("🧾 سفارش", "order:open")],
        [("👛 کیف پول", "wallet:home"), ("ℹ️ راهنما", "help:show")],
    ]
    if is_admin(update.effective_user.id):
        rows.append([("➕ افزودن محصول (ادمین)", "admin:add")])
    await update.effective_chat.send_message(txt, reply_markup=kb(rows))

# =============================
# منو و نمایش دسته‌ها/محصولات
# (محصولات با /db.list_products صفحه‌ای می‌آیند)
# =============================
async def cb_menu_root(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    await q.answer()
    rows = [[(cat, f"menu:cat:{cat}")] for cat in CATEGORIES]
    # دکمه ادمین (افزودن محصول)
    if is_admin(q.from_user.id):
        rows.append([("➕ افزودن محصول (ادمین)", "admin:add")])
    await q.edit_message_text("دستهٔ محصول را انتخاب کنید:", reply_markup=kb(rows))

async def cb_menu_cat(update: Update, context: CallbackContext) -> None:
    """فقط نمونه: لیست محصولات فعال را صفحه‌ای می‌آورد؛ می‌توانی بعداً فیلتر بر اساس دسته هم اضافه کنی."""
    q = update.callback_query
    await q.answer()
    page = int(context.matches[0].group("p") or 1)
    prods, total = db.list_products(page=page, page_size=6)

    if not prods:
        await q.edit_message_text("فعلاً محصولی ثبت نشده.")
        return

    rows = [[(f"{p['name']} — {money(p['price'])}", f"order:add:{p['id']}")] for p in prods]
    # صفحه‌بندی
    pages = (total + 5) // 6
    nav = []
    if page > 1:
        nav.append(("◀️ قبلی", f"menu:cat:{q.data.split(':')[-1]}?p={page-1}"))
    nav.append((f"{page}/{pages}", "noop"))
    if page < pages:
        nav.append(("بعدی ▶️", f"menu:cat:{q.data.split(':')[-1]}?p={page+1}"))
    rows.append(nav)
    rows.append([("بازگشت 🔙", "menu:root")])
    await q.edit_message_text("منو:", reply_markup=kb(rows))

# =============================
# سفارش: افزودن آیتم و نمایش فاکتور
# =============================
async def cb_order_add(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    await q.answer()
    user = db.get_user(q.from_user.id)
    if not user:
        db.upsert_user(q.from_user.id, q.from_user.full_name)
        user = db.get_user(q.from_user.id)
    pid = int(q.data.split(":")[-1])

    prod = db.get_product(pid)
    if not prod:
        await q.answer("محصول موجود نیست.", show_alert=True)
        return

    oid = db.open_draft_order(user["id"])
    db.add_or_increment_item(oid, pid, float(prod["price"]), inc=1)

    await q.answer("به سبد اضافه شد 🧺")
    rows = [
        [("🧾 مشاهده فاکتور", "order:invoice")],
        [("بازگشت به منو 🔙", "menu:root")],
    ]
    await q.edit_message_reply_markup(reply_markup=kb(rows))

async def cb_order_invoice(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    await q.answer()
    user = db.get_user(q.from_user.id)
    order, items = db.get_draft_with_items(user["id"])
    if not order or not items:
        await q.edit_message_text("سبد خالی است.")
        return

    lines = [f"🧾 فاکتور #{order['order_id']}"]
    s = 0
    for it in items:
        line = f"▪️ {it['name']} × {it['qty']} = {money(it['line_total'])}"
        lines.append(line)
        s += int(it["line_total"])
    lines.append(f"\nجمع کل: {money(s)}")

    rows = [
        [("➕ افزودن از منو", "menu:root")],
        [("✅ پرداخت از کیف پول", "pay:wallet"), ("💳 کارت‌به‌کارت", "pay:manual")],
        [("حذف آیتم/کاهش تعداد", "order:adjust")],
    ]
    await q.edit_message_text("\n".join(lines), reply_markup=kb(rows))

# =============================
# پرداخت
# =============================
async def cb_pay_wallet(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    await q.answer()
    user = db.get_user(q.from_user.id)
    order, items = db.get_draft_with_items(user["id"])
    if not order or not items:
        await q.edit_message_text("سبد خالی است.")
        return
    total = int(order["total_amount"])
    bal = int(db.get_balance(user["id"]))
    if bal < total:
        await q.edit_message_text(
            f"موجودی کافی نیست.\nمبلغ فاکتور: {money(total)}\nموجودی شما: {money(bal)}",
            reply_markup=kb([[("💳 شارژ کارت‌به‌کارت", "wallet:topup")], [("بازگشت", "order:invoice")]])
        )
        return

    # کسر از کیف پول
    db._exec(
        "INSERT INTO wallet_transactions(user_id, kind, amount, meta) VALUES (%s,'order',%s, jsonb_build_object('info','pay_by_wallet'))",
        (user["id"], -total),
    )
    # وضعیت سفارش paid (تریگر cashback فعال است)
    db._exec("UPDATE orders SET status='paid' WHERE order_id=%s", (order["order_id"],))

    await q.edit_message_text("پرداخت با کیف پول انجام شد ✅\nسفارش شما ثبت شد.")

# =============================
# شارژ کیف پول با رسید (Conversation)
# =============================
TOPUP_AMOUNT, TOPUP_RECEIPT = range(2)

async def cb_wallet_home(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    await q.answer()
    user = db.get_user(q.from_user.id)
    bal = db.get_balance(user["id"])
    rows = [
        [("💳 شارژ کارت‌به‌کارت", "wallet:topup")],
        [("🧾 فاکتور جاری", "order:invoice")],
        [("بازگشت به منو", "menu:root")],
    ]
    await q.edit_message_text(f"موجودی شما: {money(bal)}\nکش‌بک فعال: ۳٪", reply_markup=kb(rows))

async def cb_wallet_topup_entry(update: Update, context: CallbackContext) -> int:
    """شروع فرایند شارژ: اول مبلغ، بعد رسید."""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("مبلغ شارژ را به تومان ارسال کنید (فقط عدد):")
    return TOPUP_AMOUNT

async def h_topup_amount(update: Update, context: CallbackContext) -> int:
    txt = (update.effective_message.text or "").strip().replace(",", "")
    if not txt.isdigit() or int(txt) <= 0:
        await update.effective_chat.send_message("مبلغ نامعتبر است. فقط عدد ارسال کنید.")
        return TOPUP_AMOUNT
    context.user_data["topup_amount"] = int(txt)
    await update.effective_chat.send_message(
        "حالا اسکرین‌شات یا عکس رسید کارت‌به‌کارت را ارسال کنید.\n(اگر اشتباه شد /cancel را بزنید)"
    )
    return TOPUP_RECEIPT

async def h_topup_receipt(update: Update, context: CallbackContext) -> int:
    user = db.get_user(update.effective_user.id)
    amount = int(context.user_data.get("topup_amount", 0))
    if amount <= 0:
        await update.effective_chat.send_message("ابتدا مبلغ را بفرستید.")
        return TOPUP_AMOUNT

    msg: Message = update.effective_message
    photo_id: Optional[str] = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document and msg.document.mime_type.startswith("image/"):
        photo_id = msg.document.file_id

    if not photo_id:
        await update.effective_chat.send_message("رسید باید به‌صورت عکس/تصویر ارسال شود.")
        return TOPUP_RECEIPT

    # ارسال برای ادمین‌ها با دکمه تایید/رد
    text_admin = (
        f"درخواست شارژ کیف پول\n"
        f"کاربر: {update.effective_user.mention_html()}\n"
        f"آی‌دی: <code>{update.effective_user.id}</code>\n"
        f"مبلغ: <b>{money(amount)}</b>"
    )
    buttons = [[
        InlineKeyboardButton("✅ تایید شارژ", callback_data=f"admin:topup_ok:{user['id']}:{amount}"),
        InlineKeyboardButton("❌ رد", callback_data=f"admin:topup_rej:{user['id']}")
    ]]
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=int(admin),
                photo=photo_id,
                caption=text_admin,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        except Exception as ex:
            log.warning("send to admin failed: %s", ex)

    await update.effective_chat.send_message(
        "رسید دریافت شد ✅\nپس از بررسی ادمین، نتیجه به شما اعلام می‌شود. متشکرم."
    )
    context.user_data.pop("topup_amount", None)
    return ConversationHandler.END

async def cb_admin_topup_ok(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("فقط ادمین!", show_alert=True)
        return
    await q.answer()
    _, _, uid, amount = q.data.split(":")
    uid, amount = int(uid), int(amount)

    # ثبت تراکنش شارژ (تریگر موجودی را بالا می‌برد)
    db._exec(
        "INSERT INTO wallet_transactions(user_id, kind, amount, meta) VALUES (%s,'topup',%s, jsonb_build_object('by_admin',%s))",
        (uid, amount, q.from_user.id),
    )
    # اطلاع‌رسانی
    try:
        await context.bot.send_message(chat_id=uid, text=f"شارژ کیف پول شما تایید شد: {money(amount)} ✅")
    except Exception:
        pass
    await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n✅ تایید شد و شارژ اعمال شد.")
    
async def cb_admin_topup_rej(update: Update, context: CallbackContext) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("فقط ادمین!", show_alert=True)
        return
    await q.answer()
    _, _, uid = q.data.split(":")
    uid = int(uid)
    try:
        await context.bot.send_message(chat_id=uid, text="متاسفانه شارژ شما تایید نشد. لطفاً با ادمین در تماس باشید.")
    except Exception:
        pass
    await q.edit_message_caption(caption=(q.message.caption or "") + "\n\n⛔️ رد شد.")

async def cmd_cancel(update: Update, context: CallbackContext) -> int:
    await update.effective_chat.send_message("لغو شد.")
    context.user_data.pop("topup_amount", None)
    return ConversationHandler.END

# =============================
# افزودن محصول (ادمین) — Conversation
# =============================
AP_CAT, AP_NAME, AP_PRICE, AP_PHOTO, AP_DESC, AP_CONFIRM = range(6)

async def cb_admin_add_entry(update: Update, context: CallbackContext) -> int:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("فقط ادمین!", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    rows = [[(cat, f"admin:add:cat:{i}")] for i, cat in enumerate(CATEGORIES)]
    await q.edit_message_text("دسته را انتخاب کن:", reply_markup=kb(rows))
    return AP_CAT

async def cb_admin_add_pick_cat(update: Update, context: CallbackContext) -> int:
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[-1])
    context.user_data["ap_cat"] = CATEGORIES[idx]
    await q.edit_message_text("نام محصول را بفرست:")
    return AP_NAME

async def ap_name(update: Update, context: CallbackContext) -> int:
    name = (update.effective_message.text or "").strip()
    if not name:
        await update.effective_chat.send_message("نام معتبر نیست.")
        return AP_NAME
    context.user_data["ap_name"] = name
    await update.effective_chat.send_message("قیمت را به تومان (فقط عدد) بفرست:")
    return AP_PRICE

async def ap_price(update: Update, context: CallbackContext) -> int:
    txt = (update.effective_message.text or "").replace(",", "").strip()
    if not txt.isdigit():
        await update.effective_chat.send_message("قیمت نامعتبر است.")
        return AP_PRICE
    context.user_data["ap_price"] = int(txt)
    await update.effective_chat.send_message("عکس محصول را بفرست (یا /skip برای رد کردن):")
    return AP_PHOTO

async def ap_photo(update: Update, context: CallbackContext) -> int:
    if update.message and update.message.photo:
        context.user_data["ap_photo"] = update.message.photo[-1].file_id
    await update.effective_chat.send_message("توضیح کوتاه (یا /skip):")
    return AP_DESC

async def ap_skip(update: Update, context: CallbackContext) -> int:
    # برای photo یا description
    if "ap_photo" not in context.user_data and update.message and update.message.text == "/skip":
        await update.effective_chat.send_message("توضیح کوتاه (یا /skip):")
        return AP_DESC
    # برای description
    context.user_data["ap_desc"] = ""
    return await _ap_confirm(update, context)

async def ap_desc(update: Update, context: CallbackContext) -> int:
    context.user_data["ap_desc"] = (update.effective_message.text or "").strip()
    return await _ap_confirm(update, context)

async def _ap_confirm(update: Update, context: CallbackContext) -> int:
    name = context.user_data["ap_name"]
    price = context.user_data["ap_price"]
    cat = context.user_data["ap_cat"]
    desc = context.user_data.get("ap_desc", "")
    txt = f"افزودن محصول:\nنام: {name}\nقیمت: {money(price)}\nدسته: {cat}\nتوضیح: {desc or '-'}\n\nتایید می‌کنی؟"
    rows = [[("✅ ثبت", "admin:add:ok"), ("❌ لغو", "admin:add:cancel")]]
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=kb(rows))
    else:
        await update.effective_chat.send_message(txt, reply_markup=kb(rows))
    return AP_CONFIRM

async def cb_admin_add_ok(update: Update, context: CallbackContext) -> int:
    q = update.callback_query
    await q.answer()
    data = context.user_data
    # فعلاً فیلد دسته در جدول products نداریم؛ نام/قیمت/عکس/توضیح ذخیره می‌شود.
    db._exec(
        "INSERT INTO products(name, price, photo_file_id, description, is_active) VALUES (%s,%s,%s,%s,TRUE)",
        (data["ap_name"], data["ap_price"], data.get("ap_photo"), data.get("ap_desc", "")),
    )
    await q.edit_message_text("✅ محصول ثبت شد.")
    data.clear()
    return ConversationHandler.END

async def cb_admin_add_cancel(update: Update, context: CallbackContext) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text("لغو شد.")
    return ConversationHandler.END

# =============================
# رجیستر همهٔ هندلرها
# =============================
def build_handlers() -> List:
    # الگوهای Regex برای دسته با صفحه:  menu:cat:عنوان?p=2
    cat_pattern = r"^menu:cat:.+(?:\?p=(?P<p>\d+))?$"

    # Conversation شارژ کیف پول
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_wallet_topup_entry, pattern=r"^wallet:topup$")],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, h_topup_amount)],
            TOPUP_RECEIPT: [
                MessageHandler(filters.PHOTO | (filters.Document.IMAGE), h_topup_receipt)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="wallet_topup",
        persistent=False,
    )

    # Conversation افزودن محصول (ادمین)
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_add_entry, pattern=r"^admin:add$")],
        states={
            AP_CAT: [CallbackQueryHandler(cb_admin_add_pick_cat, pattern=r"^admin:add:cat:\d+$")],
            AP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [
                MessageHandler(filters.PHOTO, ap_photo),
                CommandHandler("skip", ap_skip),
            ],
            AP_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc),
                CommandHandler("skip", ap_skip),
            ],
            AP_CONFIRM: [
                CallbackQueryHandler(cb_admin_add_ok, pattern=r"^admin:add:ok$"),
                CallbackQueryHandler(cb_admin_add_cancel, pattern=r"^admin:add:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="admin_add_product",
        persistent=False,
    )

    return [
        CommandHandler("start", cmd_start),

        # منو
        CallbackQueryHandler(cb_menu_root, pattern=r"^menu:root$"),
        CallbackQueryHandler(cb_menu_cat, pattern=cat_pattern),

        # سفارش
        CallbackQueryHandler(cb_order_add, pattern=r"^order:add:\d+$"),
        CallbackQueryHandler(cb_order_invoice, pattern=r"^order:invoice$"),

        # پرداخت
        CallbackQueryHandler(cb_pay_wallet, pattern=r"^pay:wallet$"),

        # کیف پول
        CallbackQueryHandler(cb_wallet_home, pattern=r"^wallet:home$"),
        topup_conv,
        CallbackQueryHandler(cb_admin_topup_ok, pattern=r"^admin:topup_ok:\d+:\d+$"),
        CallbackQueryHandler(cb_admin_topup_rej, pattern=r"^admin:topup_rej:\d+$"),

        # افزودن محصول
        add_conv,
    ]
