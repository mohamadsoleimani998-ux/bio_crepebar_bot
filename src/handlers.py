from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler,
    filters
)
from .base import log, ADMIN_IDS, CURRENCY
from . import db

# ================= UI helpers =================
def main_menu_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
            [KeyboardButton("👛 کیف پول"), KeyboardButton("ℹ️ راهنما")],
        ], resize_keyboard=True
    )

def admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add_prod")],
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or "-")
    await update.message.reply_text(
        "سلام 😊\n\nاز دکمه‌های پایین استفاده کن.",
        reply_markup=main_menu_kb()
    )

# ================= Menu & Catalog =================
async def show_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cats = db.list_categories()
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"cat:{c['category_id']}")] for c in cats]
    await update.message.reply_text("دستهٔ محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(rows))

async def list_products_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, cat_id = q.data.split(":")
    items = db.list_products_by_cat(int(cat_id))
    if not items:
        await q.edit_message_text("فعلاً محصولی در این دسته ثبت نشده.")
        return
    rows=[]
    for it in items:
        rows.append([InlineKeyboardButton(f"{it['name']} — {int(it['price'])} {CURRENCY}", callback_data=f"add:{it['product_id']}")])
    rows.append([InlineKeyboardButton("« بازگشت به دسته‌ها", callback_data="back:cats")])
    await q.edit_message_text("روی محصول بزن تا به سفارش اضافه شود:", reply_markup=InlineKeyboardMarkup(rows))

async def back_to_cats_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    cats = db.list_categories()
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"cat:{c['category_id']}")] for c in cats]
    await q.edit_message_text("دستهٔ محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(rows))

async def add_item_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, pid = q.data.split(":")
    user = db.get_user_by_tg(update.effective_user.id)
    if not user:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name)
        user = db.get_user_by_tg(update.effective_user.id)
    order_id = db.open_draft_order(user["user_id"])
    p = db.get_product(int(pid))
    if not p:
        await q.answer("محصول یافت نشد/غیرفعال است.", show_alert=True); return
    db.add_or_inc_item(order_id, int(pid), float(p["price"]), 1)
    await q.answer("به سبد اضافه شد ✅", show_alert=False)

# ================= Cart / Order =================
async def cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_tg(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزن.")
        return
    order, items = db.get_draft_with_items(user["user_id"])
    if not order or not items:
        await update.message.reply_text("سبد خرید خالی است.", reply_markup=main_menu_kb()); return

    lines=[f"🧾 سبد خرید:\n"]
    total=0
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} = {int(it['line_total'])} {CURRENCY}")
        total += float(it["line_total"])
    lines.append(f"\nجمع کل: {int(total)} {CURRENCY}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ پرداخت با کیف پول", callback_data="pay:wallet"),
         InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="pay:card2card")],
    ])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)

async def pay_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    method=q.data.split(":")[1]
    user = db.get_user_by_tg(update.effective_user.id)
    order, items = db.get_draft_with_items(user["user_id"])
    if not order or not items:
        await q.edit_message_text("سبد خالی است."); return
    total=float(order["total_amount"])
    if method=="wallet":
        bal = db.get_balance(user["user_id"])
        if bal < total:
            await q.edit_message_text(f"❌ موجودی کافی نیست. موجودی: {int(bal)} {CURRENCY}")
            return
        db.add_wallet_tx(user["user_id"], "order", -total, {"order_id": order["order_id"]})
        db.set_order_status(order["order_id"], "paid", "wallet")
        await q.edit_message_text("پرداخت موفق ✅\nسفارش ثبت شد.")
    else:
        db.set_order_status(order["order_id"], "submitted", "card2card")
        await q.edit_message_text(
            "سفارش ثبت شد ✅\n"
            "لطفاً مبلغ سفارش را کارت‌به‌کارت کنید و رسید را در «👛 کیف پول → شارژ کارت‌به‌کارت» ارسال کنید.\n"
            "پس از تایید ادمین، سفارش پرداخت‌شده محسوب می‌شود."
        )

# ================= Wallet + Topup (card2card) =================
TOPUP_AMOUNT, TOPUP_PHOTO = range(2)

async def wallet_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_tg(update.effective_user.id)
    if not user:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name)
        user = db.get_user_by_tg(update.effective_user.id)
    bal = db.get_balance(user["user_id"])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 شارژ کارت‌به‌کارت", callback_data="topup:start")]
    ])
    await update.message.reply_text(f"موجودی شما: {int(bal):,} {CURRENCY}\nکش‌بک فعال: ۳٪", reply_markup=kb)

async def topup_start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    await q.message.reply_text("مبلغ شارژ (به تومان) را وارد کنید:")
    return TOPUP_AMOUNT

async def topup_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(",","").strip()
    if not txt.isdigit() or int(txt)<=0:
        await update.message.reply_text("عدد معتبر وارد کنید:")
        return TOPUP_AMOUNT
    ctx.user_data["topup_amount"]=int(txt)
    await update.message.reply_text("رسید کارت‌به‌کارت را به‌صورت *عکس* ارسال کنید.", parse_mode=ParseMode.MARKDOWN)
    return TOPUP_PHOTO

async def topup_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user_by_tg(update.effective_user.id)
    amount = ctx.user_data.get("topup_amount",0)
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس رسید را ارسال کنید.")
        return TOPUP_PHOTO
    file_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""
    req_id = db.create_topup_request(user["user_id"], amount, caption, file_id)

    # برای ادمین‌ها ارسال کن
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید", callback_data=f"topup_ok:{req_id}:{user['user_id']}:{amount}"),
        InlineKeyboardButton("❌ رد",  callback_data=f"topup_no:{req_id}:{user['user_id']}")
    ]])
    for aid in ADMIN_IDS:
        try:
            await update.get_bot().send_photo(
                chat_id=aid, photo=file_id,
                caption=f"درخواست شارژ #{req_id}\nکاربر: {user['name']} ({user['telegram_id']})\n"
                        f"مبلغ: {amount:,} {CURRENCY}\nتوضیح: {caption or '-'}",
                reply_markup=kb
            )
        except Exception as e:
            log.warning(f"send to admin failed: {e}")

    await update.message.reply_text("درخواست شارژ ثبت شد و در انتظار تایید ادمین است ✅")
    return ConversationHandler.END

async def topup_admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await q.answer("ادمین نیستید.", show_alert=True); return
    kind, req_id, user_id, *rest = q.data.split(":")
    req_id = int(req_id); user_id = int(user_id)
    if kind=="topup_ok":
        amount=float(rest[0])
        db.add_wallet_tx(user_id, "topup", amount, {"req_id":req_id,"by":update.effective_user.id})
        db.set_topup_status(req_id, "approved")
        await q.edit_message_caption((q.message.caption or "")+"\n\n✅ تایید شد.")
        try:
            await update.get_bot().send_message(chat_id=user_id, text=f"شارژ شما تایید شد. مبلغ {int(amount):,} {CURRENCY} به کیف پول‌تان افزوده شد.")
        except: pass
    else:
        db.set_topup_status(req_id, "rejected")
        await q.edit_message_caption((q.message.caption or "")+"\n\n❌ رد شد.")
        try:
            await update.get_bot().send_message(chat_id=user_id, text="درخواست شارژ شما رد شد.")
        except: pass

# ================= Admin: Add Product =================
(AP_CAT, AP_NAME, AP_PRICE, AP_DESC, AP_PHOTO, AP_SAVE) = range(6)

def is_admin(u_id:int)->bool:
    return u_id in ADMIN_IDS

async def admin_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("دسترسی ادمین ندارید.")
        return
    await update.message.reply_text("پنل ادمین:", reply_markup=admin_menu_kb())

async def admin_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await q.answer("ادمین نیستید.", show_alert=True); return
    if q.data=="admin:add_prod":
        cats = db.list_categories()
        rows=[[InlineKeyboardButton(c["name"], callback_data=f"ap_cat:{c['category_id']}")] for c in cats]
        await q.message.reply_text("دستهٔ محصول را انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return AP_CAT

async def ap_cat_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    _, cid = q.data.split(":")
    ctx.user_data["ap_cat"]=int(cid)
    await q.message.reply_text("نام محصول؟")
    return AP_NAME

async def ap_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ap_name"]=update.message.text.strip()
    await update.message.reply_text("قیمت به تومان؟")
    return AP_PRICE

async def ap_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.replace(",","").strip()
    if not t.isdigit():
        await update.message.reply_text("فقط عدد. دوباره:"); return AP_PRICE
    ctx.user_data["ap_price"]=int(t)
    await update.message.reply_text("توضیحات (اختیاری). اگر چیزی ندارید «-» بفرستید.")
    return AP_DESC

async def ap_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = update.message.text.strip()
    ctx.user_data["ap_desc"]=("" if d=="-" else d)
    await update.message.reply_text("عکس محصول را بفرست (اختیاری). اگر نمی‌خواهی «-» بفرست.")
    return AP_PHOTO

async def ap_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo_id=None
    if update.message.text and update.message.text.strip()=="-":
        photo_id=None
    else:
        if not update.message.photo:
            await update.message.reply_text("عکس معتبر یا «-» بفرست.")
            return AP_PHOTO
        photo_id = update.message.photo[-1].file_id
    ctx.user_data["ap_photo"]=photo_id

    c=ctx.user_data
    preview = f"نام: {c['ap_name']}\nقیمت: {int(c['ap_price']):,} {CURRENCY}\nتوضیح: {c['ap_desc'] or '-'}"
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ذخیره", callback_data="ap_save")],
                             [InlineKeyboardButton("❌ لغو", callback_data="ap_cancel")]])
    if photo_id:
        await update.message.reply_photo(photo=photo_id, caption=preview, reply_markup=kb)
    else:
        await update.message.reply_text(preview, reply_markup=kb)
    return AP_SAVE

async def ap_save_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if q.data=="ap_cancel":
        await q.edit_message_caption((q.message.caption or q.message.text or "") + "\nلغو شد.")
        return ConversationHandler.END
    c = ctx.user_data
    db.add_product(c["ap_cat"], c["ap_name"], c["ap_price"], c["ap_desc"], c["ap_photo"])
    await q.edit_message_caption((q.message.caption or q.message.text or "") + "\n✅ ذخیره شد.")
    return ConversationHandler.END

# ================= Builder =================
def build_handlers():
    # commands / menus
    return [
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^🍭 منو$"), show_categories),
        CallbackQueryHandler(list_products_cb, pattern=r"^cat:\d+$"),
        CallbackQueryHandler(back_to_cats_cb, pattern=r"^back:cats$"),
        CallbackQueryHandler(add_item_cb, pattern=r"^add:\d+$"),

        MessageHandler(filters.Regex("^🧾 سفارش$"), cart),
        CallbackQueryHandler(pay_cb, pattern=r"^pay:(wallet|card2card)$"),

        MessageHandler(filters.Regex("^👛 کیف پول$"), wallet_menu),
        CallbackQueryHandler(topup_start_cb, pattern=r"^topup:start$"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(topup_start_cb, pattern=r"^topup:start$")],
            states={
                TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
                TOPUP_PHOTO:  [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), topup_photo)],
            },
            fallbacks=[],
            name="topup_conv",
            persistent=False,
        ),
        CallbackQueryHandler(topup_admin_cb, pattern=r"^(topup_ok|topup_no):"),
        # admin
        CommandHandler("admin", admin_entry),
        CallbackQueryHandler(admin_menu_cb, pattern=r"^admin:"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_menu_cb, pattern=r"^admin:add_prod$")],
            states={
                AP_CAT:   [CallbackQueryHandler(ap_cat_cb, pattern=r"^ap_cat:\d+$")],
                AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
                AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
                AP_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
                AP_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ap_photo)],
                AP_SAVE:  [CallbackQueryHandler(ap_save_cb, pattern=r"^ap_(save|cancel)$")],
            },
            fallbacks=[],
            name="admin_add_prod",
            persistent=False,
        ),
    ]
