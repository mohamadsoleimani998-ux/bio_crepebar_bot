# bot.py
# -*- coding: utf-8 -*-

import os
import asyncio
import logging
from functools import wraps

import psycopg2
import psycopg2.extras

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# --------------------- Config & Logging ---------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar")

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")
if not BASE_URL:
    raise RuntimeError("ENV RENDER_EXTERNAL_URL (or WEBHOOK_URL) is missing")

# --------------------- DB Helpers ---------------------
def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def db_exec(query, params=None, fetch="none"):
    """fetch: none | one | all"""
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()

# Init tables (idempotent)
INIT_SQL = """
CREATE TABLE IF NOT EXISTS users(
    user_id BIGINT PRIMARY KEY,
    name TEXT,
    phone TEXT,
    address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wallets(
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    balance BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products(
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price BIGINT NOT NULL,
    image_file_id TEXT
);

CREATE TABLE IF NOT EXISTS music(
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    file_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topup_requests(
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now()
);
"""
db_exec(INIT_SQL)

# --------------------- Utilities ---------------------
def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not is_admin(uid):
            await update.effective_message.reply_text("⛔️ این بخش فقط برای ادمین است.")
            return
        return await func(update, context)
    return wrapper

def main_menu_kb(is_admin_flag: bool):
    rows = [
        [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📲")],
        [KeyboardButton("موزیک‌های کافه 🎵"), KeyboardButton("بازی 🎮")],
    ]
    if is_admin_flag:
        rows.append([KeyboardButton("افزودن محصول ➕"), KeyboardButton("ویرایش محصول ✏️")])
        rows.append([KeyboardButton("آپلود موزیک 🎶")])
        rows.append([KeyboardButton("تأیید شارژها ✅")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def ensure_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect name/phone/address if missing"""
    u = update.effective_user
    row = db_exec("SELECT * FROM users WHERE user_id=%s", (u.id,), "one")
    if row and row.get("name") and row.get("phone") and row.get("address"):
        return False  # already complete

    # start/continue profile wizard
    step = context.user_data.get("profile_step", "name")
    if not row:
        db_exec("INSERT INTO users(user_id,name) VALUES(%s,%s) ON CONFLICT (user_id) DO NOTHING",
                (u.id, (u.full_name or "")))
        db_exec("INSERT INTO wallets(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (u.id,))

    if step == "name":
        await update.message.reply_text("📝 لطفاً نام و نام خانوادگی را بفرستید:")
        context.user_data["profile_step"] = "got_name"
        return True
    return True

async def profile_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("profile_step")
    text = update.message.text.strip()

    if step == "got_name":
        db_exec("UPDATE users SET name=%s WHERE user_id=%s", (text, update.effective_user.id))
        context.user_data["profile_step"] = "phone"
        await update.message.reply_text("📞 لطفاً شماره تماس را بفرستید (مثلاً 09xxxxxxxxx):")
        return

    if step == "phone":
        db_exec("UPDATE users SET phone=%s WHERE user_id=%s", (text, update.effective_user.id))
        context.user_data["profile_step"] = "address"
        await update.message.reply_text("📍 لطفاً آدرس را بفرستید:")
        return

    if step == "address":
        db_exec("UPDATE users SET address=%s WHERE user_id=%s", (text, update.effective_user.id))
        context.user_data.pop("profile_step", None)
        await update.message.reply_text("✅ اطلاعات شما ذخیره شد.", reply_markup=main_menu_kb(is_admin(update.effective_user.id)))

# --------------------- Handlers ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:  # clear profile wizard if user typed /start
        context.user_data.pop("profile_step", None)

    need_profile = await ensure_profile(update, context)
    if need_profile:
        return

    await update.message.reply_text(
        "به بایو کرپ بار خوش آمدید ☕️، چطور می‌تونم کمک کنم؟",
        reply_markup=main_menu_kb(is_admin(update.effective_user.id))
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_exec("SELECT * FROM products ORDER BY id DESC", fetch="all")
    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return

    # یکجا لیست می‌کنیم + دکمه جزئیات (نمایش عکس)
    buttons = []
    text_lines = []
    for p in rows:
        text_lines.append(f"#{p['id']} • {p['name']} — {p['price']:,} تومان")
        buttons.append([InlineKeyboardButton(f"عکس/جزئیات #{p['id']}", callback_data=f"pd_{p['id']}")])

    await update.message.reply_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def product_detail_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[1])
    p = db_exec("SELECT * FROM products WHERE id=%s", (pid,), "one")
    if not p:
        await q.edit_message_text("این محصول پیدا نشد.")
        return

    cap = f"{p['name']}\nقیمت: {p['price']:,} تومان"
    if p.get("image_file_id"):
        try:
            await q.message.reply_photo(p["image_file_id"], caption=cap)
        except Exception:
            await q.message.reply_text(cap)
    else:
        await q.message.reply_text(cap)

    # اگر ادمین است، دکمه‌های ویرایش
    if is_admin(q.from_user.id):
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("ویرایش نام", callback_data=f"edit_name_{pid}"),
                InlineKeyboardButton("ویرایش قیمت", callback_data=f"edit_price_{pid}")
            ],
            [
                InlineKeyboardButton("ویرایش عکس", callback_data=f"edit_photo_{pid}"),
                InlineKeyboardButton("حذف ❌", callback_data=f"del_{pid}")
            ]
        ])
        await q.message.reply_text("مدیریت محصول:", reply_markup=kb)

# ---- Add Product (Admin) ----
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(3)

@admin_only
async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("نام محصول را ارسال کنید:")
    return ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"] = {"name": update.message.text.strip()}
    await update.message.reply_text("قیمت (به تومان) را ارسال کنید:")
    return ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").strip())
    except Exception:
        await update.message.reply_text("❗️قیمت نامعتبر است. یک عدد صحیح بفرستید.")
        return ADD_PRICE
    context.user_data["new_product"]["price"] = price
    await update.message.reply_text("اگر عکس دارید ارسال کنید؛ وگرنه /skip را بفرستید.")
    return ADD_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id if update.message.photo else None
    data = context.user_data["new_product"]
    pid = db_exec(
        "INSERT INTO products(name,price,image_file_id) VALUES(%s,%s,%s) RETURNING id",
        (data["name"], data["price"], file_id), "one"
    )["id"]
    context.user_data.pop("new_product", None)
    await update.message.reply_text(f"✅ محصول ثبت شد. (id={pid})")
    return ConversationHandler.END

async def add_product_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["new_product"]
    pid = db_exec(
        "INSERT INTO products(name,price) VALUES(%s,%s) RETURNING id",
        (data["name"], data["price"]), "one"
    )["id"]
    context.user_data.pop("new_product", None)
    await update.message.reply_text(f"✅ محصول بدون عکس ثبت شد. (id={pid})")
    return ConversationHandler.END

async def add_product_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("new_product", None)
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END

# ---- Edit Product (Admin via callbacks & /edit) ----
@admin_only
async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /edit <id>"""
    parts = (update.message.text or "").strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await update.message.reply_text("فرمت صحیح: /edit 12")
        return
    pid = int(parts[1])
    p = db_exec("SELECT * FROM products WHERE id=%s", (pid,), "one")
    if not p:
        await update.message.reply_text("محصول پیدا نشد.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ویرایش نام", callback_data=f"edit_name_{pid}")],
        [InlineKeyboardButton("ویرایش قیمت", callback_data=f"edit_price_{pid}")],
        [InlineKeyboardButton("ویرایش عکس", callback_data=f"edit_photo_{pid}")],
        [InlineKeyboardButton("حذف ❌", callback_data=f"del_{pid}")],
    ])
    await update.message.reply_text(f"مدیریت #{pid} - {p['name']}", reply_markup=kb)

async def edit_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("del_"):
        pid = int(data.split("_")[1])
        db_exec("DELETE FROM products WHERE id=%s", (pid,))
        await q.edit_message_text("✅ حذف شد.")
        return

    action, pid = data.split("_")[0] + "_" + data.split("_")[1], int(data.split("_")[2])
    context.user_data["edit_pid"] = pid

    if action == "edit_name":
        context.user_data["edit_field"] = "name"
        await q.message.reply_text("نام جدید را ارسال کنید:")
    elif action == "edit_price":
        context.user_data["edit_field"] = "price"
        await q.message.reply_text("قیمت جدید (عدد) را ارسال کنید:")
    elif action == "edit_photo":
        context.user_data["edit_field"] = "image"
        await q.message.reply_text("عکس جدید را ارسال کنید:")
    else:
        await q.message.reply_text("عملیات نامعتبر.")

async def edit_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    field = context.user_data.get("edit_field")
    pid = context.user_data.get("edit_pid")
    if not field or not pid:
        return
    if field == "name":
        db_exec("UPDATE products SET name=%s WHERE id=%s", (update.message.text.strip(), pid))
        await update.message.reply_text("✅ نام بروزرسانی شد.")
    elif field == "price":
        try:
            price = int(update.message.text.replace(",", "").strip())
        except Exception:
            await update.message.reply_text("❗️عدد نامعتبر.")
            return
        db_exec("UPDATE products SET price=%s WHERE id=%s", (price, pid))
        await update.message.reply_text("✅ قیمت بروزرسانی شد.")
    elif field == "image":
        if not update.message.photo:
            await update.message.reply_text("عکس ارسال کنید.")
            return
        file_id = update.message.photo[-1].file_id
        db_exec("UPDATE products SET image_file_id=%s WHERE id=%s", (file_id, pid))
        await update.message.reply_text("✅ عکس بروزرسانی شد.")
    context.user_data.pop("edit_field", None)
    context.user_data.pop("edit_pid", None)

# ---- Wallet ----
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = db_exec("SELECT balance FROM wallets WHERE user_id=%s", (uid,), "one")
    bal = row["balance"] if row else 0
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شارژ کیف پول", callback_data="topup")],
    ])
    await update.message.reply_text(f"موجودی شما: {bal:,} تومان", reply_markup=kb)

async def wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "topup":
        await q.message.reply_text("مبلغ شارژ را بفرستید (عدد به تومان).")
        context.user_data["topup_mode"] = "ask_amount"

async def wallet_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("topup_mode") != "ask_amount":
        return
    try:
        amount = int(update.message.text.replace(",", "").strip())
    except Exception:
        await update.message.reply_text("❗️یک عدد صحیح ارسال کنید.")
        return
    context.user_data.pop("topup_mode", None)
    req = db_exec("INSERT INTO topup_requests(user_id,amount) VALUES(%s,%s) RETURNING id",
                  (update.effective_user.id, amount), "one")
    rid = req["id"]
    await update.message.reply_text("✅ درخواست شارژ ثبت شد. پس از تأیید ادمین، موجودی شما افزایش می‌یابد.")
    # به ادمین خبر بده
    if ADMIN_ID:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("تأیید ✅", callback_data=f"topok_{rid}")],
            [InlineKeyboardButton("رد ❌", callback_data=f"topno_{rid}")],
        ])
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 درخواست شارژ #{rid}\nکاربر: {update.effective_user.mention_html()}\nمبلغ: {amount:,} تومان",
            parse_mode="HTML",
            reply_markup=kb
        )

async def topup_review_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.edit_message_text("⛔️ فقط ادمین.")
        return
    data = q.data
    rid = int(data.split("_")[1])
    row = db_exec("SELECT * FROM topup_requests WHERE id=%s", (rid,), "one")
    if not row or row["status"] != "pending":
        await q.edit_message_text("این درخواست معتبر نیست.")
        return
    if data.startswith("topok_"):
        # افزایش موجودی
        db_exec("UPDATE wallets SET balance = balance + %s WHERE user_id=%s",
                (row["amount"], row["user_id"]))
        db_exec("UPDATE topup_requests SET status='approved' WHERE id=%s", (rid,))
        await q.edit_message_text(f"✅ شارژ #{rid} تأیید شد.")
        try:
            await context.bot.send_message(row["user_id"], f"✅ شارژ شما به مبلغ {row['amount']:,} تومان تأیید شد.")
        except Exception:
            pass
    else:
        db_exec("UPDATE topup_requests SET status='rejected' WHERE id=%s", (rid,))
        await q.edit_message_text(f"⛔️ شارژ #{rid} رد شد.")
        try:
            await context.bot.send_message(row["user_id"], "⛔️ درخواست شارژ شما رد شد.")
        except Exception:
            pass

# ---- Instagram ----
INSTAGRAM_URL = "https://www.instagram.com/bio.crepebar?igsh=MXN1cnljZTN3NGhtZw=="

async def instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("رفتن به اینستاگرام 📲", url=INSTAGRAM_URL)]])
    await update.message.reply_text("پیج اینستاگرام کافه:", reply_markup=kb)

# ---- Music ----
@admin_only
async def upload_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لطفاً یک فایل موسیقی (voice/audio) بفرستید و در کپشن عنوان را بنویسید.")

async def music_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    file_id = None
    title = (update.message.caption or "موسیقی بدون نام").strip()
    if update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.voice:
        file_id = update.message.voice.file_id
    else:
        return
    db_exec("INSERT INTO music(title,file_id) VALUES(%s,%s)", (title, file_id))
    await update.message.reply_text("✅ موزیک ذخیره شد.")

async def list_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_exec("SELECT * FROM music ORDER BY id DESC LIMIT 12", fetch="all")
    if not rows:
        await update.message.reply_text("هنوز موزیکی ثبت نشده.")
        return
    for m in rows:
        try:
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=m["file_id"], caption=m["title"])
        except Exception:
            await update.message.reply_text(f"🎵 {m['title']}")

# ---- Game placeholder ----
async def game_tab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 بخش بازی به‌زودی راه می‌افته! (لیگ هفتگی و جایزه شارژ کیف پول)")

# --------------------- Router for text buttons ---------------------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == "منوی محصولات ☕️":
        await show_menu(update, context)
    elif txt == "کیف پول 💸":
        await wallet(update, context)
    elif txt == "اینستاگرام 📲":
        await instagram(update, context)
    elif txt == "افزودن محصول ➕":
        return await add_product_entry(update, context)
    elif txt == "ویرایش محصول ✏️":
        await update.message.reply_text("برای ویرایش: دستور /edit <id> را بفرستید. (مثال: /edit 12)")
    elif txt == "موزیک‌های کافه 🎵":
        await list_music(update, context)
    elif txt == "آپلود موزیک 🎶":
        await upload_music(update, context)
    elif txt == "تأیید شارژها ✅":
        await update.message.reply_text("درخواست‌های شارژ جدید به صورت خودکار برای شما ارسال می‌شوند.")
    elif txt == "بازی 🎮":
        await game_tab(update, context)
    else:
        # اگر در ویزاردها هست:
        if context.user_data.get("profile_step"):
            await profile_collector(update, context)
        else:
            await update.message.reply_text("از دکمه‌های منو استفاده کنید.", reply_markup=main_menu_kb(is_admin(update.effective_user.id)))

# --------------------- Application / Webhook ---------------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # /start + /edit
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("edit", edit_command))
    # callback queries
    app.add_handler(CallbackQueryHandler(product_detail_cb, pattern=r"^pd_\d+$"))
    app.add_handler(CallbackQueryHandler(edit_callbacks, pattern=r"^(edit_name|edit_price|edit_photo)_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(topup_review_cb, pattern=r"^(topok|topno)_\d+$"))
    app.add_handler(CallbackQueryHandler(wallet_cb, pattern=r"^topup$"))

    # add product conversation
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$") & filters.ChatType.PRIVATE, add_product_entry)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO, add_product_photo),
                CommandHandler("skip", add_product_skip_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_product_cancel)],
    ))

    # edit collector (generic)
    app.add_handler(MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_collector))

    # wallet amount collector
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_collector))

    # music upload
    app.add_handler(MessageHandler((filters.AUDIO | filters.VOICE) & filters.ChatType.PRIVATE, music_file_handler))

    # general menu router (after other specific collectors)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return app

async def on_startup(app: Application):
    # ست کردن وبهوک
    url = BASE_URL.rstrip("/") + "/" + BOT_TOKEN
    await app.bot.set_webhook(url)
    log.info("Webhook set to %s", url)

async def main():
    app = build_app()
    await on_startup(app)

    # run web service webhook
    port = int(os.getenv("PORT", "10000"))
    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,          # path باید با set_webhook یکی باشد
        webhook_url=BASE_URL.rstrip("/") + "/" + BOT_TOKEN,
        secret_token=None
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
