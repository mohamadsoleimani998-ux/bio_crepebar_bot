from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from .base import ADMIN_IDS, CASHBACK_PERCENT
import .db as db  # relative import داخل پکیج src

# حالت‌های گفت‌وگو
ASK_NAME, ASK_PHONE, ASK_ADDRESS = range(3)
ORDER_PICK, ORDER_QTY, ORDER_NOTE, ORDER_CONFIRM = range(3, 7)
TOPUP_AMOUNT, TOPUP_METHOD, TOPUP_SUBMIT = range(7, 10)

# کیبورد فارسی
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["منو", "سفارش"],
        ["کیف پول", "بازی"],
        ["ارتباط با ما"],
        ["افزودن محصول (ادمین)", "ویرایش محصول (ادمین)"]
    ],
    resize_keyboard=True
)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name)
    await update.message.reply_text(
        "سلام! به ربات خوش آمدید.\nاز کیبورد پایین یکی را انتخاب کنید.",
        reply_markup=MAIN_KB
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("از دکمه‌های پایین استفاده کنید.", reply_markup=MAIN_KB)

# ---------- اطلاعات کاربر ----------
async def ensure_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    user = db.get_user(tg_id)
    if user and user.get("phone") and user.get("address"):
        await update.message.reply_text("اطلاعات شما قبلا ثبت شده است.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    await update.message.reply_text("نام خود را وارد کنید:")
    return ASK_NAME

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    kb = ReplyKeyboardMarkup([[KeyboardButton("ارسال شماره من", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("شماره تماس را ارسال کنید:", reply_markup=kb)
    return ASK_PHONE

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    context.user_data["phone"] = phone
    await update.message.reply_text("آدرس خود را بنویسید:", reply_markup=MAIN_KB)
    return ASK_ADDRESS

async def save_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    name = context.user_data.get("name")
    phone = context.user_data.get("phone")
    db.set_user_info(update.effective_user.id, name, phone, address)
    await update.message.reply_text("اطلاعات شما ذخیره شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ---------- منو محصولات ----------
def product_rows():
    products = db.list_products()
    rows = []
    for p in products:
        text = f"{p['name']} • {p['price']} تومان"
        rows.append([InlineKeyboardButton(text, callback_data=f"order:{p['id']}")])
    if not rows:
        rows = [[InlineKeyboardButton("فعلا محصولی ثبت نشده", callback_data="noop")]]
    return rows

async def menu_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup(product_rows())
    await update.message.reply_text("منوی محصولات:", reply_markup=kb)

# ---------- سفارش ----------
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup(product_rows())
    await update.message.reply_text("یک محصول انتخاب کنید:", reply_markup=kb)
    return ORDER_PICK

async def order_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("order:"):
        return ConversationHandler.END
    prod_id = int(query.data.split(":")[1])
    context.user_data["order_prod"] = prod_id
    await query.edit_message_text("تعداد را بنویسید (مثلا 2):")
    return ORDER_QTY

async def order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("تعداد نامعتبر است. دوباره عدد بفرستید:")
        return ORDER_QTY
    context.user_data["order_qty"] = qty
    await update.message.reply_text("یادداشت/توضیح (اختیاری). اگر چیزی ندارید «-» بفرستید:")
    return ORDER_NOTE

async def order_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    context.user_data["order_note"] = "" if note == "-" else note
    # جمع کل
    prod = next((p for p in db.list_products() if p["id"] == context.user_data["order_prod"]), None)
    if not prod:
        await update.message.reply_text("محصول یافت نشد.")
        return ConversationHandler.END
    qty = context.user_data["order_qty"]
    total = prod["price"] * qty
    context.user_data["order_total"] = total
    cback = (total * CASHBACK_PERCENT) // 100
    context.user_data["order_cashback"] = cback
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید سفارش ✅", callback_data="confirm")],
        [InlineKeyboardButton("انصراف ❌", callback_data="cancel")]
    ])
    txt = f"سفارش شما:\n- {prod['name']} × {qty}\nمبلغ: {total} تومان\nکش‌بک: {cback} تومان\nتایید می‌کنید؟"
    await update.message.reply_text(txt, reply_markup=kb)
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("سفارش لغو شد.")
        return ConversationHandler.END

    tg_id = query.from_user.id
    user = db.get_user(tg_id)
    if not user or not user.get("phone") or not user.get("address"):
        await query.edit_message_text("ابتدا اطلاعات پروفایل (نام/شماره/آدرس) را تکمیل کنید.")
        return ConversationHandler.END

    prod = next((p for p in db.list_products() if p["id"] == context.user_data["order_prod"]), None)
    if not prod:
        await query.edit_message_text("محصول یافت نشد.")
        return ConversationHandler.END

    qty = context.user_data["order_qty"]
    total = context.user_data["order_total"]
    cback = context.user_data["order_cashback"]
    note = context.user_data.get("order_note")

    order_id = db.create_order(tg_id, [{"product_id": prod["id"], "qty": qty}], total, cback, note)
    # اعمال کش‌بک
    if cback > 0:
        new_balance = db.change_wallet(tg_id, cback)

    await query.edit_message_text(f"سفارش ثبت شد ✅\nشماره سفارش: {order_id}\nکش‌بک: {cback} تومان")

    # پیام برای ادمین
    for admin_id in ADMIN_IDS:
        try:
            await query.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 سفارش جدید #{order_id}\nکاربر: {query.from_user.full_name} ({tg_id})\n"
                     f"محصول: {prod['name']} × {qty}\nمبلغ: {total} تومان\nیادداشت: {note or '-'}"
            )
        except Exception:
            pass

    return ConversationHandler.END

# ---------- کیف پول ----------
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    bal = u["wallet_balance"] if u else 0
    await update.message.reply_text(
        f"موجودی کیف پول شما: {bal} تومان\nبرای شارژ عبارت «شارژ کیف پول» را بفرستید.",
        reply_markup=MAIN_KB
    )

async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مبلغ شارژ (تومان) را وارد کنید:")
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
        assert amount > 0
    except Exception:
        await update.message.reply_text("مبلغ نامعتبر است. دوباره بفرستید:")
        return TOPUP_AMOUNT
    context.user_data["topup_amount"] = amount
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("کارت به کارت", callback_data="card")],
        [InlineKeyboardButton("درگاه پرداخت (به‌زودی)", callback_data="gateway")]
    ])
    await update.message.reply_text("روش شارژ را انتخاب کنید:", reply_markup=kb)
    return TOPUP_METHOD

async def topup_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = "card_to_card" if q.data == "card" else "gateway"
    context.user_data["topup_method"] = method
    topup_id = db.create_topup(q.from_user.id, context.user_data["topup_amount"], method)
    await q.edit_message_text(
        f"درخواست شارژ ثبت شد (#{topup_id}).\n"
        f"روش: {'کارت به کارت' if method=='card_to_card' else 'درگاه'}\n"
        f"لطفاً رسید را برای ادمین ارسال کنید تا تایید شود."
    )
    # اطلاع به ادمین
    for admin_id in ADMIN_IDS:
        try:
            await q.bot.send_message(
                admin_id, f"🟡 درخواست شارژ #{topup_id} از {q.from_user.full_name} ({q.from_user.id})"
            )
        except Exception:
            pass
    return ConversationHandler.END

# ---------- بخش بازی (ساده) ----------
async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import random
    n = random.randint(1, 6)
    await update.message.reply_text(f"🎲 عدد شما: {n}\n(صرفاً برای سرگرمی)")

# ---------- ارتباط با ما ----------
async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را بنویسید تا برای ادمین ارسال شود.")
    return 100  # state موقتی

async def contact_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"📩 پیام کاربر {update.effective_user.id}:\n{msg}")
        except Exception:
            pass
    await update.message.reply_text("پیامتان ارسال شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ---------- ادمین: افزودن/ویرایش/حذف محصول ----------
async def admin_add_product(update, context):
    if not is_admin(update.effective_user.id):
        return
    # فرمت: افزودن محصول (ادمین) نام | قیمت | لینک‌عکس(اختیاری)
    text = (update.message.text or "").replace("افزودن محصول (ادمین)", "").strip()
    if "|" not in text:
        await update.message.reply_text("فرمت: نام | قیمت | لینک‌عکس(اختیاری)")
        return
    parts = [p.strip() for p in text.split("|")]
    name = parts[0]
    try:
        price = int(parts[1])
    except Exception:
        await update.message.reply_text("قیمت نامعتبر.")
        return
    photo = parts[2] if len(parts) > 2 else None
    db.add_product(name, price, photo)
    await update.message.reply_text("محصول اضافه شد ✅")

async def admin_edit_product(update, context):
    if not is_admin(update.effective_user.id):
        return
    # فرمت: ویرایش محصول (ادمین) id | نام(اختیاری) | قیمت(اختیاری) | لینک‌عکس(اختیاری)
    text = (update.message.text or "").replace("ویرایش محصول (ادمین)", "").strip()
    if "|" not in text:
        await update.message.reply_text("فرمت: id | نام(اختیاری) | قیمت(اختیاری) | لینک‌عکس(اختیاری)")
        return
    parts = [p.strip() for p in text.split("|")]
    prod_id = int(parts[0])
    name = parts[1] or None if len(parts) > 1 else None
    price = int(parts[2]) if len(parts) > 2 and parts[2] else None
    photo = parts[3] if len(parts) > 3 and parts[3] else None
    db.update_product(prod_id, name, price, photo)
    await update.message.reply_text("محصول بروزرسانی شد ✅")

async def admin_delete_product(update, context):
    if not is_admin(update.effective_user.id):
        return
    # فرمت: حذف محصول id
    parts = (update.message.text or "").split()
    if len(parts) < 3:
        await update.message.reply_text("فرمت: حذف محصول id")
        return
    prod_id = int(parts[2])
    db.delete_product(prod_id)
    await update.message.reply_text("محصول حذف شد 🗑️")

# ---------- ثبت هندلرها ----------
def register(application: Application):
    # استارت و کمک
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(MessageHandler(filters.Regex("^(/help|راهنما)$"), help_cmd))

    # منو
    application.add_handler(MessageHandler(filters.Regex("^(منو|/products)$"), menu_products))

    # پروفایل/اطلاعات
    profile_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ثبت اطلاعات$"), ensure_user_info)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler((filters.CONTACT | filters.TEXT) & ~filters.COMMAND, ask_address)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_user_info)],
        },
        fallbacks=[]
    )
    application.add_handler(profile_conv)

    # سفارش
    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(سفارش|/order)$"), order_start)],
        states={
            ORDER_PICK: [CallbackQueryHandler(order_pick)],
            ORDER_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)],
            ORDER_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_note)],
            ORDER_CONFIRM: [CallbackQueryHandler(order_confirm)],
        },
        fallbacks=[]
    )
    application.add_handler(order_conv)

    # کیف پول
    application.add_handler(MessageHandler(filters.Regex("^(کیف پول|/wallet)$"), wallet))
    topup_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^شارژ کیف پول$"), topup_start)],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_METHOD: [CallbackQueryHandler(topup_method)],
        },
        fallbacks=[]
    )
    application.add_handler(topup_conv)

    # بازی/ارتباط
    application.add_handler(MessageHandler(filters.Regex("^(بازی|/game)$"), game))
    contact_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(ارتباط با ما|/contact)$"), contact)],
        states={100: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_forward)]},
        fallbacks=[]
    )
    application.add_handler(contact_conv)

    # ادمین‌ها
    application.add_handler(MessageHandler(filters.Regex("^افزودن محصول \\(ادمین\\).+"), admin_add_product))
    application.add_handler(MessageHandler(filters.Regex("^ویرایش محصول \\(ادمین\\).+"), admin_edit_product))
    application.add_handler(MessageHandler(filters.Regex("^حذف محصول \\d+$"), admin_delete_product))

def startup_warmup(application: Application):
    # ساخت جداول در استارت
    db.init_db()
