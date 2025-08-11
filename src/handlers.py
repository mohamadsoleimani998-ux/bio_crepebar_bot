import os
import re
from typing import Any
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)

import db

ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS","").replace(" ","").split(",") if x}
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "0"))

# ======= کمک‌ها =======
def is_admin(user_id:int)->bool:
    return user_id in ADMIN_IDS

def main_menu_kb():
    rows = [
        ["🛍 منو", "🧾 ثبت سفارش"],
        ["👛 کیف پول", "🎮 بازی"],
        ["☎️ ارتباط با ما", "ℹ️ راهنما"],
    ]
    if ADMIN_IDS:
        rows.append(["🛠 مدیریت"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.full_name)
    text = (
        "سلام! به ربات خوش آمدید.\n"
        "از منوی زیر یکی را انتخاب کنید."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنما:\n"
        "• 🛍 منو: مشاهده‌ی محصولات\n"
        "• 🧾 ثبت سفارش: افزودن کالا و نهایی‌سازی\n"
        "• 👛 کیف پول: مشاهده/شارژ کیف پول\n"
        "• 🎮 بازی: حدس عدد ساده با جایزه‌ی کوچک!\n"
        "• ☎️ ارتباط با ما: ارسال پیام به ادمین"
    )

# ======= محصولات =======
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE, offset:int=0):
    prods = db.list_products(offset=offset)
    if not prods:
        await update.message.reply_text("فعلاً محصولی ثبت نشده است.", reply_markup=main_menu_kb())
        return
    for p in prods:
        cap = f"#{p['id']} — {p['name']}\nقیمت: {p['price']:,} تومان"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add:{p['id']}"),
        ]])
        if p.get("photo_file_id"):
            await update.message.reply_photo(p["photo_file_id"], caption=cap, reply_markup=kb)
        else:
            await update.message.reply_text(cap, reply_markup=kb)

    nav = InlineKeyboardMarkup([[InlineKeyboardButton("صفحه بعد ▶️", callback_data=f"page:{offset+6}")]])
    if len(prods)==6:
        await update.message.reply_text("...", reply_markup=nav)

async def products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_products(update, context, 0)

async def products_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    if data.startswith("page:"):
        off = int(data.split(":")[1])
        # پیام ناوبری جدید
        await q.message.reply_text("در حال بارگذاری...", reply_markup=None)
        class DummyMsg:  # برای استفاده مجدد از show_products
            def __init__(self, chat_id): self.chat_id=chat_id
        update.message = q.message  # reuse
        await show_products(update, context, offset=off)

    elif data.startswith("add:"):
        pid = int(data.split(":")[1])
        cart = db.get_cart(uid)
        found = False
        for it in cart:
            if it["id"] == pid:
                it["qty"] += 1
                found = True
                break
        if not found:
            cart.append({"id": pid, "qty": 1})
        db.save_cart(uid, cart)
        p = db.get_product(pid)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"«{p['name']}» به سبد اضافه شد. برای ثبت نهایی از «🧾 ثبت سفارش» استفاده کنید.")

# ======= سفارش =======
ORDER_NAME, ORDER_PHONE, ORDER_ADDR, ORDER_CONFIRM = range(4)

def _cart_detail(uid:int):
    cart = db.get_cart(uid)
    if not cart: return ([], 0, "سبد خرید شما خالی است.")
    lines, total = [], 0
    for it in cart:
        p = db.get_product(it["id"])
        if not p: 
            continue
        line_total = p["price"] * it["qty"]
        total += line_total
        lines.append(f"#{p['id']} {p['name']} x{it['qty']} = {line_total:,}")
    txt = "سبد خرید:\n" + "\n".join(lines) + f"\n\nجمع کل: {total:,} تومان"
    return (cart, total, txt)

async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cart, total, txt = _cart_detail(uid)
    if not cart:
        await update.message.reply_text("برای سفارش ابتدا از «🛍 منو» محصول اضافه کنید.", reply_markup=main_menu_kb())
        return ConversationHandler.END
    await update.message.reply_text(txt + "\n\nنام و نام خانوادگی را وارد کنید:")
    return ORDER_NAME

async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("شماره تماس را وارد کنید (مثال: 09xxxxxxxxx):")
    return ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = re.sub(r"\D", "", update.message.text)
    if not phone.startswith("09") or len(phone) != 11:
        await update.message.reply_text("شماره‌ی نامعتبر. دوباره ارسال کنید:")
        return ORDER_PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text("آدرس کامل را وارد کنید:")
    return ORDER_ADDR

async def order_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    addr = update.message.text.strip()
    name = context.user_data["name"]
    phone = context.user_data["phone"]
    db.update_profile(uid, name, phone, addr)

    cart, total, txt = _cart_detail(uid)
    cashback = (total * CASHBACK_PERCENT) // 100
    bal = db.wallet_balance(uid)

    confirm_txt = (
        f"{txt}\n\n"
        f"نام: {name}\n"
        f"تلفن: {phone}\n"
        f"آدرس: {addr}\n"
        f"موجودی کیف پول: {bal:,} تومان\n"
        f"کش‌بک این سفارش: {cashback:,} تومان\n\n"
        "تأیید می‌کنید؟"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و پرداخت از کیف پول", callback_data="order:pay_wallet")],
        [InlineKeyboardButton("❌ انصراف", callback_data="order:cancel")]
    ])
    await update.message.reply_text(confirm_txt, reply_markup=kb)
    return ORDER_CONFIRM

async def order_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "order:cancel":
        await q.edit_message_text("سفارش لغو شد.", reply_markup=None)
        return ConversationHandler.END

    # پرداخت از کیف پول
    cart, total, _ = _cart_detail(uid)
    bal = db.wallet_balance(uid)
    if bal < total:
        await q.edit_message_text("موجودی کیف پول کافی نیست. از «👛 کیف پول» شارژ کنید.", reply_markup=None)
        return ConversationHandler.END

    cashback = (total * CASHBACK_PERCENT) // 100
    # برداشت
    db.wallet_change(uid, -total, "order", {"total": total})
    order_id = db.create_order(uid, cart, total, cashback)
    # کش‌بک
    if cashback > 0:
        db.wallet_change(uid, cashback, "cashback", {"order_id": order_id})
    # خالی کردن سبد
    db.clear_cart(uid)

    # پیام به کاربر
    await q.edit_message_text(f"سفارش #{order_id} ثبت شد ✅\n"
                              f"مبلغ: {total:,} تومان\n"
                              f"کش‌بک واریز شد: {cashback:,} تومان")

    # پیام به ادمین
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"سفارش جدید #{order_id} از {q.from_user.full_name} (id:{uid})")
        except Exception:
            pass

    return ConversationHandler.END

# ======= کیف پول =======
async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = db.wallet_balance(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کارت به کارت", callback_data="topup:manual")],
        [InlineKeyboardButton("💳 درگاه پرداخت (به‌زودی)", callback_data="topup:gateway")],
        [InlineKeyboardButton("🧾 گردش تراکنش‌ها", callback_data="wallet:tx")]
    ])
    await update.message.reply_text(f"موجودی کیف پول شما: {bal:,} تومان", reply_markup=kb)

TOPUP_AMOUNT = range(1)

async def wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "wallet:tx":
        txs = db.user_transactions(uid)
        if not txs:
            await q.edit_message_text("تراکنشی ثبت نشده است.", reply_markup=None)
            return
        lines = []
        for t in txs:
            sign = "+" if t["amount"]>0 else ""
            lines.append(f"{t['ttype']}: {sign}{t['amount']:,}")
        await q.edit_message_text("آخرین تراکنش‌ها:\n" + "\n".join(lines), reply_markup=None)
        return

    if data == "topup:gateway":
        await q.edit_message_text("اتصال به درگاه به‌زودی فعال می‌شود.", reply_markup=None)
        return

    if data == "topup:manual":
        await q.edit_message_text("مبلغ شارژ (تومان) را ارسال کنید:", reply_markup=None)
        return

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    amt_txt = re.sub(r"\D","", update.message.text)
    if not amt_txt:
        await update.message.reply_text("مبلغ نامعتبر. فقط عدد بفرستید:")
        return
    amount = int(amt_txt)
    # برای سادگی: تأیید ادمین لازم ندارد؛ مستقیم واریز نمایشی
    db.wallet_change(uid, amount, "topup", {"method":"manual"})
    bal = db.wallet_balance(uid)
    await update.message.reply_text(f"واریز انجام شد ✅\nموجودی جدید: {bal:,} تومان", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ======= بازی ساده =======
GAME_WAIT = range(1)

async def game_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import random
    n = random.randint(1, 5)
    context.user_data["game_n"] = n
    await update.message.reply_text("🎮 بازی حدس عدد (۱ تا ۵). عدد را بفرست:")
    return GAME_WAIT

async def game_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        g = int(re.sub(r"\D","", update.message.text))
    except:
        await update.message.reply_text("یک عدد بین ۱ تا ۵ بفرست:")
        return GAME_WAIT
    n = context.user_data.get("game_n", 0)
    if g == n:
        prize = 1000  # جایزه‌ی کوچک
        db.wallet_change(update.effective_user.id, prize, "game", {"guess": g})
        await update.message.reply_text(f"👏 درست حدس زدی! {prize:,} تومان به کیف پولت اضافه شد.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(f"نشد! عدد درست {n} بود.", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ======= ارتباط با ما =======
CONTACT_WAIT = range(1)

async def contact_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را بفرستید تا برای ادمین ارسال شود:")
    return CONTACT_WAIT

async def contact_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"📩 پیام کاربر {update.effective_user.id}:\n{txt}")
        except Exception:
            pass
    await update.message.reply_text("پیام شما ارسال شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ======= پنل مدیریت (افزودن/ویرایش محصول) =======
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(3)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    kb = ReplyKeyboardMarkup([["➕ افزودن محصول", "✏️ ویرایش/حذف"], ["بازگشت"]], resize_keyboard=True)
    await update.message.reply_text("منوی مدیریت:", reply_markup=kb)

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرستید:")
    return ADD_NAME

async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان) را بفرستید:")
    return ADD_PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_txt = re.sub(r"\D","", update.message.text)
    if not price_txt:
        await update.message.reply_text("قیمت نامعتبر. فقط عدد بفرستید:")
        return ADD_PRICE
    context.user_data["p_price"] = int(price_txt)
    await update.message.reply_text("عکس محصول را ارسال کنید (اختیاری). اگر عکس ندارید «عدم ارسال» بنویسید:")
    return ADD_PHOTO

async def admin_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    name = context.user_data["p_name"]
    price = context.user_data["p_price"]
    db.add_product(name, price, photo_id)
    await update.message.reply_text("محصول ثبت شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ساده: ویرایش/حذف با ارسال «id قیمت جدید» یا «حذف id»
async def admin_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    txt = update.message.text.strip()
    if txt.startswith("حذف"):
        try:
            pid = int(re.sub(r"\D","", txt))
            db.update_product(pid, active=False)
            await update.message.reply_text("محصول غیرفعال شد.")
        except:
            await update.message.reply_text("فرمت نامعتبر. مثال: «حذف 12»")
    else:
        m = re.findall(r"\d+", txt)
        if len(m) >= 2:
            pid, new_price = int(m[0]), int(m[1])
            db.update_product(pid, price=new_price)
            await update.message.reply_text("قیمت به‌روزرسانی شد.")
        else:
            await update.message.reply_text("فرمت نامعتبر. مثال: «12 450000»")

# ======= روتر کیبورد فارسی =======
async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "🛍 منو":
        return await products_cmd(update, context)
    if text == "🧾 ثبت سفارش":
        return await order_entry(update, context)
    if text == "👛 کیف پول":
        return await wallet_cmd(update, context)
    if text == "🎮 بازی":
        return await game_entry(update, context)
    if text == "☎️ ارتباط با ما":
        return await contact_entry(update, context)
    if text == "ℹ️ راهنما":
        return await help_cmd(update, context)
    if text == "🛠 مدیریت":
        return await admin_menu(update, context)
    if text == "➕ افزودن محصول":
        return await admin_add_start(update, context)
    if text == "✏️ ویرایش/حذف":
        await update.message.reply_text("مثال برای ویرایش قیمت: «12 450000»\nبرای حذف: «حذف 12»")
        return
    if text == "بازگشت":
        return await start(update, context)

# ======= ثبت هندلرها =======
def register(application: Application) -> None:
    # راه‌اندازی دیتابیس
    db.init_db()

    # دستورات کلاسیک (در صورت نیاز)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("products", products_cmd))
    application.add_handler(CommandHandler("wallet", wallet_cmd))

    # کال‌بک‌ها
    application.add_handler(CallbackQueryHandler(products_cb, pattern=r"^(add:|page:)"))
    application.add_handler(CallbackQueryHandler(order_confirm_cb, pattern=r"^order:(pay_wallet|cancel)$"))
    application.add_handler(CallbackQueryHandler(wallet_cb, pattern=r"^(topup:|wallet:tx|topup:gateway)"))

    # گفتگوهای سفارش
    application.add_handler(ConversationHandler(
        name="order_flow",
        entry_points=[MessageHandler(filters.Regex("^🧾 ثبت سفارش$"), order_entry)],
        states={
            ORDER_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ORDER_ADDR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, order_addr)],
            ORDER_CONFIRM: [CallbackQueryHandler(order_confirm_cb, pattern=r"^order:(pay_wallet|cancel)$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    ))

    # تاپ‌آپ دستی
    application.add_handler(ConversationHandler(
        name="topup_flow",
        entry_points=[CallbackQueryHandler(wallet_cb, pattern=r"^topup:manual$")],
        states={},
        fallbacks=[]
    ))
    application.add_handler(MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND, topup_amount))

    # بازی
    application.add_handler(ConversationHandler(
        name="game_flow",
        entry_points=[MessageHandler(filters.Regex("^🎮 بازی$"), game_entry)],
        states={GAME_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, game_guess)]},
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    ))

    # ارتباط با ما
    application.add_handler(ConversationHandler(
        name="contact_flow",
        entry_points=[MessageHandler(filters.Regex("^☎️ ارتباط با ما$"), contact_entry)],
        states={CONTACT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_send)]},
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    ))

    # افزودن محصول (ادمین)
    application.add_handler(ConversationHandler(
        name="admin_add_product",
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن محصول$"), admin_add_start)],
        states={
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_price)],
            ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.Regex("^عدم ارسال$")) & ~filters.COMMAND, admin_add_photo)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    ))

    # ویرایش/حذف
    application.add_handler(MessageHandler(filters.Regex("^(✏️ ویرایش/حذف|حذف .+|\\d+ \\d+)$"), admin_edit))

    # روتر متن دکمه‌های فارسی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router_text))
