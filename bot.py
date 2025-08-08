# bot.py
import os
import logging
from typing import Optional, Tuple, List

import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes,
    filters
)

# ---------------------- Config & Logging ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("crepebar")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL")
INSTAGRAM_URL = os.environ.get("INSTAGRAM_URL", "https://instagram.com/")

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

# ---------------------- DB helpers ----------------------
def db_conn():
    """Open new connection each time (prevents recursive re-entry)."""
    return psycopg2.connect(DATABASE_URL)

def db_execute(sql: str, params: Tuple = ()):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()

def db_query(sql: str, params: Tuple = ()) -> List[dict]:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

def db_query_one(sql: str, params: Tuple = ()) -> Optional[dict]:
    rows = db_query(sql, params)
    return rows[0] if rows else None

# ---------------------- Migrations ----------------------
def run_migrations():
    # users
    db_execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE,
        name TEXT,
        phone TEXT,
        address TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # wallets
    db_execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        balance BIGINT DEFAULT 0
    );
    """)
    # products
    db_execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price BIGINT NOT NULL,
        description TEXT,
        photo_file_id TEXT,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # recharges
    db_execute("""
    CREATE TABLE IF NOT EXISTS recharges (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        amount BIGINT NOT NULL,
        tx_note TEXT,
        status TEXT DEFAULT 'pending', -- pending/approved/rejected
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # musics (only file_id + title)
    db_execute("""
    CREATE TABLE IF NOT EXISTS musics (
        id SERIAL PRIMARY KEY,
        title TEXT,
        file_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)

# ---------------------- Constants & States ----------------------
# Conversations
(ASK_NAME, ASK_PHONE, ASK_ADDRESS) = range(3)
(ADD_NAME, ADD_PRICE, ADD_DESC, ADD_PHOTO) = range(10, 14)
(EDIT_CHOOSE, EDIT_FIELD, EDIT_VALUE, EDIT_PHOTO) = range(20, 24)
(RECHARGE_AMOUNT, RECHARGE_NOTE) = range(30, 32)
(ADD_MUSIC_TITLE, ADD_MUSIC_FILE) = range(40, 42)

# ---------------------- UI Builders ----------------------
def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📲"), KeyboardButton("بازی 🎮")],
        [KeyboardButton("موزیک 🎵")],
    ]
    if is_admin:
        rows.append([KeyboardButton("افزودن محصول ➕"), KeyboardButton("ویرایش محصول ✏️")])
        rows.append([KeyboardButton("افزودن موزیک 🎼")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ---------------------- Helpers ----------------------
def ensure_user_and_wallet(tg_id: int):
    user = db_query_one("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    if not user:
        db_execute("INSERT INTO users (tg_id) VALUES (%s)", (tg_id,))
        user = db_query_one("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    wal = db_query_one("SELECT * FROM wallets WHERE user_id=%s", (user["id"],))
    if not wal:
        db_execute("INSERT INTO wallets (user_id, balance) VALUES (%s, 0)", (user["id"],))
    return user

async def send_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    is_admin = update.effective_user.id == ADMIN_ID
    await update.effective_chat.send_message(text, reply_markup=main_menu(is_admin))

def need_profile(user: dict) -> bool:
    return not user.get("name") or not user.get("phone") or not user.get("address")

# ---------------------- Start & Profile ----------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_and_wallet(update.effective_user.id)
    if need_profile(u):
        await update.message.reply_text("به بایو کرپ بار خوش آمدی ☕️\nبرای ادامه، اول مشخصاتت رو ثبت کنیم.\nنام و نام‌خانوادگی؟")
        return ASK_NAME
    await send_home(update, ctx, "به بایو کرپ بار خوش آمدی ☕️")
    return ConversationHandler.END

async def ask_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    db_execute("UPDATE users SET name=%s WHERE tg_id=%s", (name, update.effective_user.id))
    await update.message.reply_text("شماره تماس؟")
    return ASK_PHONE

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    db_execute("UPDATE users SET phone=%s WHERE tg_id=%s", (phone, update.effective_user.id))
    await update.message.reply_text("آدرس کامل؟")
    return ASK_ADDRESS

async def ask_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    addr = update.message.text.strip()
    db_execute("UPDATE users SET address=%s WHERE tg_id=%s", (addr, update.effective_user.id))
    await send_home(update, ctx, "اطلاعاتت ذخیره شد ✅")
    return ConversationHandler.END

async def cancel_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ثبت مشخصات لغو شد.")
    return ConversationHandler.END

# ---------------------- Products: add/list/edit ----------------------
async def add_product_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("اسم محصول؟")
    return ADD_NAME

async def add_product_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان)؟")
    return ADD_PRICE

async def add_product_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("قیمت باید عدد باشد. دوباره بفرست.")
        return ADD_PRICE
    ctx.user_data["p_price"] = price
    await update.message.reply_text("توضیح کوتاه؟ (اختیاری، یا بزن «–»)")
    return ADD_DESC

async def add_product_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "–":
        desc = ""
    ctx.user_data["p_desc"] = desc
    await update.message.reply_text("عکس محصول را ارسال کن.")
    return ADD_PHOTO

async def add_product_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("عکس نامعتبر. دوباره عکس بفرست.")
        return ADD_PHOTO
    file_id = update.message.photo[-1].file_id
    name = ctx.user_data["p_name"]
    price = ctx.user_data["p_price"]
    desc = ctx.user_data["p_desc"]
    db_execute(
        "INSERT INTO products (name, price, description, photo_file_id) VALUES (%s,%s,%s,%s)",
        (name, price, desc, file_id),
    )
    await update.message.reply_text("محصول با موفقیت ثبت شد ✅")
    return ConversationHandler.END

async def list_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prods = db_query("SELECT * FROM products WHERE active=TRUE ORDER BY id DESC LIMIT 20")
    if not prods:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    # ارسال لیستی: اول یک پیام خلاصه، سپس تصاویر
    lines = [f"#{p['id']} — {p['name']} • {p['price']:,} تومان" for p in prods]
    await update.message.reply_text("منوی محصولات:\n" + "\n".join(lines))
    media = []
    for p in prods[:10]:  # تا ۱۰ تا در یک آلبوم
        cap = f"#{p['id']} — {p['name']}\nقیمت: {p['price']:,} تومان\n{p.get('description','') or ''}".strip()
        if p.get("photo_file_id"):
            media.append(InputMediaPhoto(p["photo_file_id"], caption=cap))
    if media:
        await update.message.reply_media_group(media)

# ---- Edit product (admin) ----
async def edit_product_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    prods = db_query("SELECT id, name FROM products WHERE active=TRUE ORDER BY id DESC LIMIT 30")
    if not prods:
        await update.message.reply_text("محصولی برای ویرایش وجود ندارد.")
        return ConversationHandler.END
    btns = [[InlineKeyboardButton(f"#{p['id']} — {p['name']}", callback_data=f"pick:{p['id']}")] for p in prods]
    await update.message.reply_text("کدام محصول؟", reply_markup=InlineKeyboardMarkup(btns))
    return EDIT_CHOOSE

async def edit_choose_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    ctx.user_data["edit_pid"] = pid
    btns = [
        [InlineKeyboardButton("نام", callback_data="field:name"),
         InlineKeyboardButton("قیمت", callback_data="field:price")],
        [InlineKeyboardButton("توضیح", callback_data="field:desc"),
         InlineKeyboardButton("عکس", callback_data="field:photo")],
        [InlineKeyboardButton("حذف/غیرفعال", callback_data="field:disable")]
    ]
    await q.edit_message_text("کدام بخش را ویرایش کنیم؟", reply_markup=InlineKeyboardMarkup(btns))
    return EDIT_FIELD

async def edit_field_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.split(":")[1]
    ctx.user_data["edit_field"] = field
    if field == "photo":
        await q.edit_message_text("عکس جدید را ارسال کن.")
        return EDIT_PHOTO
    elif field == "disable":
        db_execute("UPDATE products SET active=FALSE WHERE id=%s", (ctx.user_data["edit_pid"],))
        await q.edit_message_text("محصول غیرفعال شد.")
        return ConversationHandler.END
    else:
        prompt = {"name": "نام جدید؟", "price": "قیمت جدید؟", "desc": "توضیح جدید؟"}[field]
        await q.edit_message_text(prompt)
        return EDIT_VALUE

async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = ctx.user_data["edit_field"]
    val = update.message.text.strip()
    pid = ctx.user_data["edit_pid"]
    if field == "price":
        try:
            val = int(val)
        except ValueError:
            await update.message.reply_text("قیمت باید عدد باشد.")
            return EDIT_VALUE
    col = {"name": "name", "price": "price", "desc": "description"}[field]
    db_execute(f"UPDATE products SET {col}=%s WHERE id=%s", (val, pid))
    await update.message.reply_text("ویرایش انجام شد ✅")
    return ConversationHandler.END

async def edit_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("عکس نامعتبر. دوباره بفرست.")
        return EDIT_PHOTO
    file_id = update.message.photo[-1].file_id
    pid = ctx.user_data["edit_pid"]
    db_execute("UPDATE products SET photo_file_id=%s WHERE id=%s", (file_id, pid))
    await update.message.reply_text("عکس به‌روزرسانی شد ✅")
    return ConversationHandler.END

# ---------------------- Wallet / Recharge ----------------------
async def wallet_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_and_wallet(update.effective_user.id)
    user = db_query_one("SELECT id FROM users WHERE tg_id=%s", (update.effective_user.id,))
    wal = db_query_one("SELECT balance FROM wallets WHERE user_id=%s", (user["id"],))
    bal = wal["balance"] if wal else 0
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("درخواست شارژ", callback_data="recharge:start")]
    ])
    await update.message.reply_text(f"موجودی کیف پول: {bal:,} تومان", reply_markup=kb)

async def recharge_start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("مبلغ شارژ (تومان)؟")
    return RECHARGE_AMOUNT

async def recharge_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("عدد نامعتبر. دوباره بفرست.")
        return RECHARGE_AMOUNT
    ctx.user_data["rc_amount"] = amount
    await update.message.reply_text("کد/توضیح واریزی (اختیاری) را بفرست یا «–» بزن.")
    return RECHARGE_NOTE

async def recharge_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    if note == "–":
        note = ""
    user = db_query_one("SELECT id FROM users WHERE tg_id=%s", (update.effective_user.id,))
    db_execute(
        "INSERT INTO recharges (user_id, amount, tx_note, status) VALUES (%s,%s,%s,'pending')",
        (user["id"], ctx.user_data["rc_amount"], note),
    )
    rid = db_query_one("SELECT id FROM recharges WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user["id"],))["id"]

    # notify admin
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تایید ✅", callback_data=f"rc_ok:{rid}"),
         InlineKeyboardButton("رد ❌", callback_data=f"rc_no:{rid}")]
    ])
    await update.message.reply_text("درخواست شارژ ثبت شد و منتظر تایید است. ✅")
    try:
        await update.get_bot().send_message(
            chat_id=ADMIN_ID,
            text=f"درخواست شارژ #{rid}\nکاربر: {update.effective_user.id}\nمبلغ: {ctx.user_data['rc_amount']:,}",
            reply_markup=kb
        )
    except Exception as e:
        log.warning("Admin notify failed: %s", e)
    return ConversationHandler.END

async def recharge_admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data, rid = q.data.split(":")
    rid = int(rid)
    rec = db_query_one("SELECT * FROM recharges WHERE id=%s", (rid,))
    if not rec or rec["status"] != "pending":
        await q.edit_message_text("درخواست نامعتبر یا قبلا بررسی شده است.")
        return
    if data == "rc_ok":
        # add balance
        wal = db_query_one("SELECT * FROM wallets WHERE user_id=%s", (rec["user_id"],))
        new_bal = (wal["balance"] if wal else 0) + rec["amount"]
        db_execute("UPDATE wallets SET balance=%s WHERE id=%s", (new_bal, wal["id"]))
        db_execute("UPDATE recharges SET status='approved' WHERE id=%s", (rid,))
        await q.edit_message_text(f"شارژ #{rid} تایید شد. موجودی جدید: {new_bal:,}")
        # inform user
        u = db_query_one("SELECT tg_id FROM users WHERE id=%s", (rec["user_id"],))
        try:
            await update.get_bot().send_message(u["tg_id"], f"شارژ شما تایید شد. مبلغ: {rec['amount']:,} تومان ✅")
        except:  # noqa
            pass
    else:
        db_execute("UPDATE recharges SET status='rejected' WHERE id=%s", (rid,))
        await q.edit_message_text("شارژ رد شد.")

# ---------------------- Instagram / Music / Game ----------------------
async def instagram(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("مشاهده پیج", url=INSTAGRAM_URL)]])
    await update.message.reply_text("اینستاگرام ما:", reply_markup=kb)

async def music_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db_query("SELECT * FROM musics ORDER BY id DESC LIMIT 20")
    if not rows:
        await update.message.reply_text("فعلا موزیکی ثبت نشده.")
        return
    for r in rows:
        try:
            await update.message.chat.send_audio(audio=r["file_id"], caption=r.get("title") or "")
        except Exception:
            await update.message.reply_text(r.get("title") or "موزیک")

async def add_music_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("عنوان موزیک؟")
    return ADD_MUSIC_TITLE

async def add_music_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_title"] = update.message.text.strip()
    await update.message.reply_text("فایل موزیک را ارسال کن (Audio).")
    return ADD_MUSIC_FILE

async def add_music_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.audio:
        await update.message.reply_text("فایل صوتی ارسال کن.")
        return ADD_MUSIC_FILE
    file_id = update.message.audio.file_id
    title = ctx.user_data.get("m_title", "")
    db_execute("INSERT INTO musics (title, file_id) VALUES (%s,%s)", (title, file_id))
    await update.message.reply_text("موزیک ذخیره شد ✅")
    return ConversationHandler.END

async def game_placeholder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بخش بازی به‌زودی راه‌اندازی می‌شود 🎮")

# ---------------------- Router ----------------------
async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    ensure_user_and_wallet(uid)

    if text in ["/start", "شروع", "منو", "بازگشت"]:
        await start(update, ctx)
        return

    if text == "منوی محصولات ☕️":
        await list_products(update, ctx); return
    if text == "افزودن محصول ➕":
        await add_product_entry(update, ctx); return
    if text == "ویرایش محصول ✏️":
        await edit_product_entry(update, ctx); return
    if text == "کیف پول 💸":
        await wallet_menu(update, ctx); return
    if text == "اینستاگرام 📲":
        await instagram(update, ctx); return
    if text == "موزیک 🎵":
        await music_list(update, ctx); return
    if text == "افزودن موزیک 🎼":
        await add_music_entry(update, ctx); return
    if text == "بازی 🎮":
        await game_placeholder(update, ctx); return

    await update.message.reply_text("دستور ناشناس. از منو استفاده کن.")

# ---------------------- Main ----------------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # Profile flow
    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        per_user=True,
        per_chat=True,
        name="profile",
        persistent=False,
    )

    # Add product
    add_prod = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$"), add_product_entry)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_product_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="add_product",
        persistent=False,
    )

    # Edit product
    edit_prod = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ویرایش محصول ✏️$"), edit_product_entry)],
        states={
            EDIT_CHOOSE: [CallbackQueryHandler(edit_choose_cb, pattern=r"^pick:\d+$")],
            EDIT_FIELD: [CallbackQueryHandler(edit_field_cb, pattern=r"^field:(name|price|desc|photo|disable)$")],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO, edit_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="edit_product",
        persistent=False,
    )

    # Recharge
    recharge_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(recharge_start_cb, pattern="^recharge:start$")],
        states={
            RECHARGE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_amount)],
            RECHARGE_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recharge_note)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="recharge",
        persistent=False,
    )

    # Add music
    add_music = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن موزیک 🎼$"), add_music_entry)],
        states={
            ADD_MUSIC_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_music_title)],
            ADD_MUSIC_FILE: [MessageHandler(filters.AUDIO, add_music_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="add_music",
        persistent=False,
    )

    # Admin callbacks for recharge
    app.add_handler(CallbackQueryHandler(recharge_admin_cb, pattern=r"^(rc_ok|rc_no):\d+$"))

    # Conversations
    app.add_handler(profile_conv)
    app.add_handler(add_prod)
    app.add_handler(edit_prod)
    app.add_handler(recharge_conv)
    app.add_handler(add_music)

    # Text router last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Commands
    app.add_handler(CommandHandler("instagram", instagram))
    app.add_handler(CommandHandler("menu", start))

    return app

def main():
    # Run migrations safely (each opens/closes its own connection)
    run_migrations()

    app = build_app()
    # polling (مناسب Render Web Service بدون پورت)
    log.info("Starting bot with polling…")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
