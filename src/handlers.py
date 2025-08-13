from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from .base import (
    log, ADMIN_IDS, WELCOME_TEXT, MAIN_KEYBOARD,
    DEFAULT_CASHBACK, CARD_NUMBER
)
from . import db
import re

# ---------- States ----------
ADD_PRODUCT_STATE = {}
REGISTER_STATE = {}

# ---------- Keyboards ----------
def _main_kb():
    return ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# ---------- Normalizer ----------
# حذف ZWJ/RTL marks/اموجی/سایر سیمبل‌ها؛ نگه‌داشتن فقط حروف و اعداد فارسی/لاتین و فاصله
ZWJ_RTL = "".join(chr(c) for c in [0x200C, 0x200D, 0x200F, 0x061C])
_EMOJI_SYMBOLS = re.compile(fr"[{re.escape(ZWJ_RTL)}\u2066-\u2069]|[^\w\s\u0600-\u06FF]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")
# یکسان‌سازی ی و ك/كاف عربی، هٔ… برای مقایسه مطمئن
TRANSLATE = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک",
    "ۀ": "ه", "ة": "ه",
})

def norm(txt: str) -> str:
    if not txt:
        return ""
    t = txt.translate(TRANSLATE)
    t = _EMOJI_SYMBOLS.sub(" ", t)
    t = _MULTI_SPACE.sub(" ", t).strip()
    return t.casefold()

def has_any(txt: str, *keywords: str) -> bool:
    nt = norm(txt)
    return any(k in nt for k in keywords)

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_main_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "دستورات:\n"
        "/start – شروع\n"
        "/menu – نمایش منو\n"
        "/addproduct – اضافه‌کردن محصول (ادمین)\n"
        "/register – ثبت‌نام/ویرایش اطلاعات\n"
        "/wallet – موجودی و شارژ کیف پول\n"
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update)

# ---------- Register flow ----------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    REGISTER_STATE[update.effective_user.id] = "NAME"
    await update.message.reply_text("نام خود را بفرستید:")

# ---------- Helpers ----------
async def show_menu(update: Update):
    try:
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
    except Exception as e:
        log.exception("menu error: %s", e)
        await update.message.reply_text("❌ خطای غیرمنتظره در نمایش منو.")

# ---------- Routers ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    raw = update.message.text or ""
    n = norm(raw)
    log.info("TEXT IN: raw='%s' | norm='%s' | uid=%s", raw, n, u.id)

    # ثبت‌نام
    if REGISTER_STATE.get(u.id) == "NAME":
        db.set_user_profile(u.id, name=raw.strip())
        REGISTER_STATE[u.id] = "PHONE"
        await update.message.reply_text("شماره تماس را بفرستید:")
        return

    if REGISTER_STATE.get(u.id) == "PHONE":
        db.set_user_profile(u.id, phone=raw.strip())
        REGISTER_STATE[u.id] = "ADDR"
        await update.message.reply_text("آدرس را بفرستید:")
        return

    if REGISTER_STATE.get(u.id) == "ADDR":
        db.set_user_profile(u.id, address=raw.strip())
        REGISTER_STATE.pop(u.id, None)
        await update.message.reply_text("✅ ثبت اطلاعات انجام شد.", reply_markup=_main_kb())
        return

    # دکمه‌ها (با و بدون اموجی/جا‌به‌جایی)
    if has_any(raw, "منو", "menu"):
        await show_menu(update)
        return

    if has_any(raw, "سفارش", "order"):
        await update.message.reply_text("نام محصول و تعداد را بنویس (مثال: «اسپرسو x2»). (دموی ساده)")
        return

    if has_any(raw, "کیف پول", "کیف", "wallet"):
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

    if has_any(raw, "بازی", "game"):
        await update.message.reply_text("🎲 به‌زودی…")
        return

    if has_any(raw, "ارتباط با ما", "ارتباط", "contact"):
        await update.message.reply_text("پیامت را بنویس؛ برای ادمین ارسال می‌شود.")
        return

    if has_any(raw, "راهنما", "help"):
        await help_cmd(update, context)
        return

    # --- جریان ادمین Add Product ---
    st = ADD_PRODUCT_STATE.get(u.id)
    if st and st.get("await") == "PRICE":
        try:
            numbers = "".join(ch for ch in raw if ch.isdigit())
            price = int(numbers)
            ADD_PRODUCT_STATE[u.id]["price"] = price
            ADD_PRODUCT_STATE[u.id]["await"] = "PHOTO"
            await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»).")
        except Exception:
            await update.message.reply_text("قیمت نامعتبر است. فقط عدد بفرست.")
        return

    if st and st.get("await") == "DESC":
        try:
            desc = raw.strip()
            if has_any(desc, "بدون توضیحات"):
                desc = None
            st = ADD_PRODUCT_STATE.pop(u.id, {})
            row = db.add_product(st.get("name"), st.get("price"), st.get("photo"), desc)
            await update.message.reply_text(f"✅ محصول ثبت شد: {row['name']} – {row['price']:,} تومان")
        except Exception as e:
            log.exception("add_product: %s", e)
            await update.message.reply_text("❌ خطای غیرمنتظره. لطفاً دوباره تلاش کنید.")
        return

    await update.message.reply_text("متوجه نشدم؛ از کیبورد پایین استفاده کن یا /help .")

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    st = ADD_PRODUCT_STATE.get(u.id, {})
    if st.get("await") == "PHOTO":
        photo = update.message.photo[-1]
        ADD_PRODUCT_STATE[u.id]["photo"] = photo.file_id
        ADD_PRODUCT_STATE[u.id]["await"] = "DESC"
        await update.message.reply_text("توضیحات کوتاه (اختیاری) را بفرست. اگر نمی‌خواهی بنویس «بدون توضیحات».")
        return

# Admin: add product
async def addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("فقط ادمین‌ها اجازه این کار را دارند.")
        return
    ADD_PRODUCT_STATE[update.effective_user.id] = {"await": "NAME"}
    await update.message.reply_text("نام محصول را بفرست:")

# First-step name catcher for addproduct
async def any_text_first(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    st = ADD_PRODUCT_STATE.get(u.id)
    if st and st.get("await") == "NAME":
        st["name"] = (update.message.text or "").strip()
        st["await"] = "PRICE"
        await update.message.reply_text("قیمت (تومان) را بفرست:")
        return
    await text_router(update, context)

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

async def admin_add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        _, tg, amount = (update.message.text or "").split()
        tg = int(tg); amount = int(amount)
        new_bal = db.wallet_change(tg, amount, "TOPUP", "MANUAL_ADMIN")
        await update.message.reply_text(f"✅ موجودی کاربر {tg} به {new_bal:,} تومان رسید.")
    except Exception:
        await update.message.reply_text("نحوه استفاده: /credit <telegram_id> <amount>")

def build_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),
        CommandHandler("menu", menu_cmd),      # میانبر منو
        CommandHandler("register", register),
        CommandHandler("addproduct", addproduct),
        CommandHandler("wallet", text_router),
        CommandHandler("credit", admin_add_credit),

        CallbackQueryHandler(on_callback),
        MessageHandler(filters.PHOTO, photo_router),
        MessageHandler(filters.TEXT & ~filters.COMMAND, any_text_first),
    ]
