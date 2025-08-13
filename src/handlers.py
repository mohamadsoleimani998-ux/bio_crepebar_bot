from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from .base import (
    log, ADMIN_IDS, WELCOME_TEXT, MAIN_KEYBOARD,
    DEFAULT_CASHBACK, CARD_NUMBER
)
from . import db
import traceback

# --- States in-memory (ساده و سبک) ---
ADD_PRODUCT_STATE = {}   # tg_id -> {"name":..., "price":..., "photo":..., "desc":...}
REGISTER_STATE = {}      # tg_id -> "NAME"/"PHONE"/"ADDR"

# --- Helpers ---
def _main_kb():
    return ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_main_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "دستورات:\n"
        "/start – شروع\n"
        "/addproduct – اضافه‌کردن محصول (ادمین)\n"
        "/register – ثبت‌نام/ویرایش اطلاعات\n"
        "/wallet – موجودی و شارژ کیف پول\n"
    )

# ---------- Register / Profile ----------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    REGISTER_STATE[update.effective_user.id] = "NAME"
    await update.message.reply_text("نام خود را بفرستید:")

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مسیر دهی پیام‌های متنی (کیبورد فارسی + استیت‌ها)"""
    u = update.effective_user
    txt = (update.message.text or "").strip()

    # --- جریان ثبت‌نام ---
    if REGISTER_STATE.get(u.id) == "NAME":
        db.set_user_profile(u.id, name=txt)
        REGISTER_STATE[u.id] = "PHONE"
        await update.message.reply_text("شماره تماس را بفرستید:")
        return
    if REGISTER_STATE.get(u.id) == "PHONE":
        db.set_user_profile(u.id, phone=txt)
        REGISTER_STATE[u.id] = "ADDR"
        await update.message.reply_text("آدرس را بفرستید:")
        return
    if REGISTER_STATE.get(u.id) == "ADDR":
        db.set_user_profile(u.id, address=txt)
        REGISTER_STATE.pop(u.id, None)
        await update.message.reply_text("✅ ثبت اطلاعات انجام شد.", reply_markup=_main_kb())
        return

    # --- کیبورد اصلی ---
    if txt.endswith("منو") or txt == "🍬 منو":
        prods = db.list_products()
        if not prods:
            await update.message.reply_text("فعلاً محصولی ثبت نشده.")
            return
        for p in prods:
            cap = f"🍩 <b>{p['name']}</b>\nقیمت: {p['price']:,} تومان"
            if p.get("description"):
                cap += f"\n— {p['description']}"
            if p.get("photo_file_id"):
                await update.message.reply_photo(p["photo_file_id"], caption=cap)
            else:
                await update.message.reply_text(cap)
        return

    if txt.endswith("سفارش") or txt == "🧾 سفارش":
        await update.message.reply_text("نام محصول و تعداد را بنویس (مثال: «اسپرسو x2»). (دموی ساده)")
        return

    if txt.endswith("کیف پول") or txt == "👛 کیف پول":
        user = db.get_user_by_tg(u.id)
        bal = user["wallet"] if user else 0
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("شارژ کارت‌به‌کارت", callback_data="wallet_topup")
        ]])
        await update.message.reply_text(
            f"💳 موجودی شما: <b>{bal:,} تومان</b>\n"
            f"کش‌بک فعال: {DEFAULT_CASHBACK}%\n", reply_markup=kb
        )
        return

    if txt.endswith("بازی") or txt == "🎮 بازی":
        await update.message.reply_text("🎲 به‌زودی…")
        return

    if txt.endswith("ارتباط با ما") or txt == "📞 ارتباط با ما":
        await update.message.reply_text("پیامت را بنویس؛ برای ادمین ارسال می‌شود.")
        return

    if txt.endswith("راهنما") or txt == "ℹ️ راهنما":
        await help_cmd(update, context)
        return

    # --- جریان ادمین Add Product ---
    if ADD_PRODUCT_STATE.get(u.id, {}).get("await") == "PRICE":
        try:
            # فقط ارقام فارسی/لاتین را نگه‌دار
            numbers = "".join(ch for ch in txt if ch.isdigit())
            price = int(numbers)
            ADD_PRODUCT_STATE[u.id]["price"] = price
            ADD_PRODUCT_STATE[u.id]["await"] = "PHOTO"
            await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»).")
        except Exception as e:
            await update.message.reply_text("قیمت نامعتبر است. فقط عدد بفرست.")
        return

    if ADD_PRODUCT_STATE.get(u.id, {}).get("await") == "DESC":
        try:
            desc = txt if txt != "بدون توضیحات" else None
            st = ADD_PRODUCT_STATE.pop(u.id, {})
            row = db.add_product(st.get("name"), st.get("price"), st.get("photo"), desc)
            await update.message.reply_text(f"✅ محصول ثبت شد: {row['name']} – {row['price']:,} تومان")
        except Exception as e:
            log.exception("add_product: %s", e)
            await update.message.reply_text("❌ خطای غیرمنتظره. لطفاً دوباره تلاش کنید.")
        return

    # اگر به هیچ‌جا نخورد
    await update.message.reply_text("متوجه نشدم؛ از کیبورد پایین استفاده کن یا /help .")

# عکس در حالت AddProduct
async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    st = ADD_PRODUCT_STATE.get(u.id, {})
    if st.get("await") == "PHOTO":
        photo = update.message.photo[-1]
        ADD_PRODUCT_STATE[u.id]["photo"] = photo.file_id
        ADD_PRODUCT_STATE[u.id]["await"] = "DESC"
        await update.message.reply_text("توضیحات کوتاه (اختیاری) را بفرست. اگر نمی‌خواهی بنویس «بدون توضیحات».")
        return

# ادمین: شروع افزودن محصول
async def addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("فقط ادمین‌ها اجازه این کار را دارند.")
        return
    ADD_PRODUCT_STATE[update.effective_user.id] = {"await": "NAME"}
    await update.message.reply_text("نام محصول را بفرست:")

# گرفتن نام محصول (اولین قدم AddProduct)
async def any_text_first(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    st = ADD_PRODUCT_STATE.get(u.id)
    if st and st.get("await") == "NAME":
        st["name"] = (update.message.text or "").strip()
        st["await"] = "PRICE"
        await update.message.reply_text("قیمت (تومان) را بفرست:")
        return
    # سایر متن‌ها را به روتر اصلی بده
    await text_router(update, context)

# کلیک‌ها (مثلاً شارژ کیف‌پول)
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet_topup":
        await q.message.reply_text(
            "شارژ کارت‌به‌کارت:\n"
            f"💳 {CARD_NUMBER}\n"
            "مبلغ را واریز کنید و رسید یا مبلغ را همینجا ارسال کنید.\n"
            "پس از تایید ادمین شارژ می‌شود."
        )

# فرمان ساده شارژ (ادمین تایید کند)
async def admin_add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        # مثال: /credit 1606170079 50000
        _, tg, amount = update.message.text.split()
        tg = int(tg); amount = int(amount)
        new_bal = db.wallet_change(tg, amount, "TOPUP", "MANUAL_ADMIN")
        await update.message.reply_text(f"✅ موجودی کاربر {tg} به {new_bal:,} تومان رسید.")
    except Exception:
        await update.message.reply_text("نحوه استفاده: /credit <telegram_id> <amount>")

def build_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),
        CommandHandler("register", register),
        CommandHandler("addproduct", addproduct),
        CommandHandler("wallet", text_router),
        CommandHandler("credit", admin_add_credit),  # فقط برای ادمین
        CallbackQueryHandler(on_callback),

        # ترتیب مهم است:
        MessageHandler(filters.PHOTO, photo_router),
        MessageHandler(filters.TEXT & ~filters.COMMAND, any_text_first),
    ]
