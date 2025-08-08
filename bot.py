import os, sqlite3, logging
from typing import Tuple
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ---------------- Config ----------------
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 1606170079          # <— chat_id شما
DB = "db.sqlite3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("crepebar")

# ---------------- DB ----------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_id TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT, phone TEXT, address TEXT,
            wallet INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            receipt_photo TEXT
        )""")
init_db()

# ---------------- Keyboards ----------------
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ منوی محصولات", callback_data="menu")],
        [InlineKeyboardButton("💸 کیف پول", callback_data="wallet")],
        [InlineKeyboardButton("📱 اینستاگرام", url="https://www.instagram.com/bio.crepebar")]
    ])

def admin_reply_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("➕ افزودن محصول")],
         [KeyboardButton("📋 لیست محصولات")]],
        resize_keyboard=True
    )

# ---------------- /start ----------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    await update.message.reply_text("به بایو کرپ بار خوش اومدید ☕️", reply_markup=main_menu_kb())

# ---------------- Wallet ----------------
async def cb_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    with db() as c:
        row = c.execute("SELECT wallet FROM users WHERE user_id=?", (uid,)).fetchone()
    await q.message.reply_text(f"💰 موجودی کیف پول: {row['wallet']:,} تومان")

# ---------------- Menu (list) ----------------
async def cb_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    with db() as c:
        rows = c.execute("SELECT id, name, price FROM products ORDER BY id DESC").fetchall()
    if not rows:
        return await q.message.reply_text("هنوز محصولی ثبت نشده است.")
    # لیست محصولات
    for r in rows:
        pid, name, price = r["id"], r["name"], r["price"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ نمایش عکس", callback_data=f"p:photo:{pid}")],
            [InlineKeyboardButton("🛒 سفارش", callback_data=f"p:order:{pid}")]
        ])
        await q.message.reply_text(f"• {name}\n💵 قیمت: {price:,} تومان", reply_markup=kb)

# ---------------- Product photo tab ----------------
async def cb_product_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    pid = int(q.data.split(":")[-1])
    with db() as c:
        row = c.execute("SELECT name, price, photo_id FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        return await q.message.reply_text("محصول یافت نشد.")
    if row["photo_id"]:
        await q.message.reply_photo(
            photo=row["photo_id"],
            caption=f"{row['name']}\n💵 {row['price']:,} تومان"
        )
    else:
        await q.message.reply_text("برای این محصول هنوز عکسی ثبت نشده است.")

# ---------------- Order flow ----------------
GET_NAME, GET_PHONE, GET_ADDRESS, WAIT_RECEIPT = range(4)

def set_user_step(ctx: ContextTypes.DEFAULT_TYPE, step: int, pid: int = None):
    ctx.user_data["step"] = step
    if pid is not None:
        ctx.user_data["pid"] = pid

async def cb_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    pid = int(q.data.split(":")[-1])
    set_user_step(ctx, GET_NAME, pid)
    await q.message.reply_text("لطفاً نام خود را وارد کنید:")

async def msg_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    step = ctx.user_data.get("step")

    # ادمین شورتکات‌ها
    if uid == ADMIN_ID and text == "➕ افزودن محصول":
        ctx.user_data["add_state"] = "ask_name"
        return await update.message.reply_text("نام محصول را بفرستید:", reply_markup=admin_reply_kb())
    if uid == ADMIN_ID and text == "📋 لیست محصولات":
        with db() as c:
            rows = c.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
        if not rows:
            return await update.message.reply_text("محصولی ثبت نشده.", reply_markup=admin_reply_kb())
        lines = [f"#{r['id']} • {r['name']} — {r['price']:,} تومان" for r in rows]
        return await update.message.reply_text("\n".join(lines), reply_markup=admin_reply_kb())

    # افزودن محصول (ادمین)
    if uid == ADMIN_ID and ctx.user_data.get("add_state") == "ask_name":
        ctx.user_data["new_name"] = text.strip()
        ctx.user_data["add_state"] = "ask_price"
        return await update.message.reply_text("قیمت محصول (فقط عدد)؟", reply_markup=admin_reply_kb())

    if uid == ADMIN_ID and ctx.user_data.get("add_state") == "ask_price":
        if not text.isdigit():
            return await update.message.reply_text("فقط عدد وارد کن.", reply_markup=admin_reply_kb())
        ctx.user_data["new_price"] = int(text)
        ctx.user_data["add_state"] = "ask_photo"
        return await update.message.reply_text("حالا عکس محصول را **به صورت عکس** بفرست.", reply_markup=admin_reply_kb())

    # مرحله سفارش کاربر
    if step == GET_NAME:
        ctx.user_data["name"] = text.strip()
        set_user_step(ctx, GET_PHONE)
        return await update.message.reply_text("شماره تماس را وارد کنید:")
    if step == GET_PHONE:
        ctx.user_data["phone"] = text.strip()
        set_user_step(ctx, GET_ADDRESS)
        return await update.message.reply_text("آدرس کامل را وارد کنید:")
    if step == GET_ADDRESS:
        ctx.user_data["address"] = text.strip()
        # ذخیره اطلاعات کاربر
        with db() as c:
            c.execute("""INSERT INTO users(user_id,name,phone,address)
                         VALUES(?,?,?,?)
                         ON CONFLICT(user_id) DO UPDATE SET
                           name=excluded.name, phone=excluded.phone, address=excluded.address""",
                      (uid, ctx.user_data["name"], ctx.user_data["phone"], ctx.user_data["address"]))
        set_user_step(ctx, WAIT_RECEIPT)
        return await update.message.reply_text(
            "لطفاً مبلغ را کارت‌به‌کارت کنید و **عکس رسید** را ارسال نمایید.\n"
            "⬅️ بعد از دریافت رسید، سفارش شما بررسی و تایید می‌شود."
        )

    # پیام‌های عمومی خارج از فلوی سفارش: نادیده/راهنما
    return

async def photo_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # افزودن عکس محصول (ادمین)
    if uid == ADMIN_ID and ctx.user_data.get("add_state") == "ask_photo":
        pid_photo = update.message.photo[-1].file_id
        name = ctx.user_data.pop("new_name")
        price = ctx.user_data.pop("new_price")
        ctx.user_data.pop("add_state", None)
        with db() as c:
            c.execute("INSERT INTO products(name,price,photo_id) VALUES(?,?,?)", (name, price, pid_photo))
        return await update.message.reply_text("✅ محصول با عکس ثبت شد.", reply_markup=admin_reply_kb())

    # رسید سفارش کاربر
    if ctx.user_data.get("step") == WAIT_RECEIPT and "pid" in ctx.user_data:
        receipt_id = update.message.photo[-1].file_id
        pid = ctx.user_data["pid"]
        with db() as c:
            c.execute("INSERT INTO orders(user_id,product_id,status,receipt_photo) VALUES(?,?,?,?)",
                      (uid, pid, "در انتظار تایید", receipt_id))
        # اطلاع به ادمین
        await update.message.reply_text("✅ رسید دریافت شد. سفارش شما در صف تایید است.")
        try:
            await update.get_bot().send_photo(
                chat_id=ADMIN_ID, photo=receipt_id,
                caption=f"رسید جدید از {uid}\nمحصول #{pid}\nنام: {ctx.user_data.get('name')}\n"
                        f"شماره: {ctx.user_data.get('phone')}\nآدرس: {ctx.user_data.get('address')}"
            )
        except Exception as e:
            log.error("Notify admin failed: %s", e)
        # پایان جریان
        ctx.user_data.clear()
        return
    # اگر عکس غیرمرتبط بود، نادیده
    return

# ---------------- Admin panel ----------------
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔️ دسترسی ندارید.")
    await update.message.reply_text("پنل ادمین:", reply_markup=admin_reply_kb())

# ---------------- Wiring ----------------
def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing in env")

    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Menu tabs
    app.add_handler(CallbackQueryHandler(cb_menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(cb_wallet, pattern="^wallet$"))
    app.add_handler(CallbackQueryHandler(cb_product_photo, pattern=r"^p:photo:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_order, pattern=r"^p:order:\d+$"))

    # Text & Photo routers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
