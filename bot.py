# bot.py
# Bio Crepebar Bot — PTB v20 (polling)
import os, re, logging, asyncio
from typing import Tuple

import psycopg2
import psycopg2.extras

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------------- Logging ----------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bio.crepebar")

# ---------------- ENV ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")
INSTAGRAM_URL = os.environ.get("INSTAGRAM_URL", "https://www.instagram.com/bio.crepebar")
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "3"))

raw_dsn = os.environ.get("DATABASE_URL", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not raw_dsn:
    raise RuntimeError("ENV DATABASE_URL is missing")

# قبول هر فرمتی و استخراج URL معتبر
m = re.search(r"(?:postgresql|postgres)://[^\s'\"`]+", raw_dsn)
if not m:
    raise RuntimeError(f"Invalid DATABASE_URL: {raw_dsn}")
DATABASE_URL = m.group(0)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
# channel_binding لازم نیست
DATABASE_URL = re.sub(r"([?&])channel_binding=require(&|$)", lambda k: k.group(1) if k.group(2) else "", DATABASE_URL)
# اگر sslmode نبود اضافه کن
if "sslmode=" not in DATABASE_URL:
    DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

# ---------------- DB Helpers ----------------
def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

def db_exec(sql: str, params: Tuple = (), fetch: str = "none"):
    with db_conn() as con, con.cursor() as cur:
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return None

def init_db():
    db_exec("""
    CREATE TABLE IF NOT EXISTS users(
      user_id BIGINT PRIMARY KEY,
      name TEXT,
      phone TEXT,
      address TEXT,
      wallet INTEGER DEFAULT 0
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS products(
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      price INTEGER NOT NULL,
      photo_id TEXT
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS orders(
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      product_id INTEGER NOT NULL,
      status TEXT NOT NULL,          -- pending/paid/approved/rejected
      deliver_method TEXT,           -- delivery/pickup
      receipt_photo TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS topups(
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      amount INTEGER NOT NULL,
      status TEXT NOT NULL,          -- pending/approved/rejected
      receipt_photo TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS music(
      id SERIAL PRIMARY KEY,
      title TEXT NOT NULL,
      file_id TEXT NOT NULL
    );
    """)
    log.info("DB initialized")

# ---------------- UI ----------------
def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_ID

def main_kb(is_admin_flag: bool):
    rows = [
        [KeyboardButton("منوی محصولات ☕"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📲")],
    ]
    if is_admin_flag:
        rows.append([KeyboardButton("➕ افزودن محصول"), KeyboardButton("🛠 ویرایش محصول")])
        rows.append([KeyboardButton("🎵 موزیک"), KeyboardButton("🎮 بازی")])
        rows.append([KeyboardButton("🧑‍💻 پنل ادمین")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ---------------- Start & Profile Wizard ----------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    init_db()
    uid = update.effective_user.id
    db_exec("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (uid,))
    # اگر پروفایل ناقص است، ویزارد را شروع کن
    row = db_exec("SELECT name,phone,address FROM users WHERE user_id=%s", (uid,), fetch="one")
    if not row or not (row["name"] and row["phone"] and row["address"]):
        ctx.user_data["profile_stage"] = "get_name"
        await update.message.reply_text("اول اسمت رو بگو:")
        return
    await update.message.reply_text(
        "به بایو کِرپ‌بار خوش اومدی ☕️",
        reply_markup=main_kb(is_admin(update))
    )

async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()

    # --- profile wizard ---
    stage = ctx.user_data.get("profile_stage")
    if stage == "get_name":
        name = txt
        if not name:
            return await update.message.reply_text("اسم خالیه! دوباره بفرست.")
        ctx.user_data["name"] = name
        ctx.user_data["profile_stage"] = "get_phone"
        return await update.message.reply_text("شماره تماس (با 09…):")
    if stage == "get_phone":
        if not re.fullmatch(r"0\d{10}", txt):
            return await update.message.reply_text("شماره نامعتبره، با 11 رقم بفرست.")
        ctx.user_data["phone"] = txt
        ctx.user_data["profile_stage"] = "get_address"
        return await update.message.reply_text("آدرس تحویل:")
    if stage == "get_address":
        addr = txt
        if not addr:
            return await update.message.reply_text("آدرس خالیه! دوباره بفرست.")
        db_exec("""
            INSERT INTO users(user_id,name,phone,address) VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone, address=EXCLUDED.address
        """, (uid, ctx.user_data["name"], ctx.user_data["phone"], addr))
        ctx.user_data.pop("profile_stage", None)
        return await update.message.reply_text("اطلاعات ذخیره شد ✅", reply_markup=main_kb(is_admin(update)))

    # --- main actions ---
    if txt == "منوی محصولات ☕":
        rows = db_exec("SELECT id,name,price,photo_id FROM products ORDER BY id DESC", fetch="all")
        if not rows:
            return await update.message.reply_text("هنوز محصولی ثبت نشده.")
        for r in rows:
            caption = f"#{r['id']} — {r['name']}\nقیمت: {r['price']} هزار تومان"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("سفارش 🛒", callback_data=f"order:{r['id']}")]])
            if r["photo_id"]:
                await update.message.reply_photo(r["photo_id"], caption=caption, reply_markup=kb)
            else:
                await update.message.reply_text(caption, reply_markup=kb)
        return

    if txt == "کیف پول 💸":
        row = db_exec("SELECT wallet FROM users WHERE user_id=%s", (uid,), fetch="one")
        w = row["wallet"] if row else 0
        await update.message.reply_text(
            f"موجودی: {w} تومان\nبرای شارژ، مبلغ را عددی بفرست (مثلاً 50000)."
        )
        ctx.user_data["await_topup_amount"] = True
        return

    if ctx.user_data.get("await_topup_amount"):
        only_digits = re.sub(r"[^\d]", "", txt)
        if not only_digits:
            return await update.message.reply_text("فقط عدد بفرست (مثلاً 50000).")
        amt = int(only_digits)
        ctx.user_data["await_topup_amount"] = False
        ctx.user_data["topup_amount"] = amt
        ctx.user_data["await_topup_receipt"] = True
        return await update.message.reply_text(
            f"مبلغ {amt} تومان ✅\nکارت‌به‌کارت به این کارت:\n💳 6037-xxxx-xxxx-xxxx\n"
            "به‌نام: Bio Crepebar\n\nرسید را به صورت *عکس* ارسال کن.", parse_mode="Markdown"
        )

    if txt == "اینستاگرام 📲":
        return await update.message.reply_text(f"اینستاگرام کافه: {INSTAGRAM_URL}")

    # --- admin only ---
    if txt == "➕ افزودن محصول":
        if not is_admin(update):
            return await update.message.reply_text("این گزینه فقط برای ادمین است.")
        ctx.user_data["add_stage"] = "name"
        return await update.message.reply_text("نام محصول را بفرست:")

    if txt == "🛠 ویرایش محصول":
        if not is_admin(update):
            return await update.message.reply_text("این گزینه فقط برای ادمین است.")
        ctx.user_data["edit_stage"] = "ask_id"
        return await update.message.reply_text("آیدی محصول برای ویرایش را بفرست:")

    if txt == "🎵 موزیک":
        return await update.message.reply_text("فعلاً آپلود موزیک فقط برای ادمین است. بعداً فعال می‌کنیم.")
    if txt == "🎮 بازی":
        return await update.message.reply_text("بخش بازی به‌زودی فعال می‌شود 🕹️")

    # --- add product flow (admin) ---
    if ctx.user_data.get("add_stage") == "name" and is_admin(update):
        ctx.user_data["new_product_name"] = txt
        ctx.user_data["add_stage"] = "price"
        return await update.message.reply_text("قیمت (هزار تومان) را بفرست:")
    if ctx.user_data.get("add_stage") == "price" and is_admin(update):
        if not re.fullmatch(r"\d+", txt):
            return await update.message.reply_text("فقط عدد قیمت (هزار تومان).")
        price = int(txt)
        row = db_exec(
            "INSERT INTO products(name,price) VALUES (%s,%s) RETURNING id",
            (ctx.user_data["new_product_name"], price), fetch="one"
        )
        ctx.user_data["new_product_id"] = row["id"]
        ctx.user_data["add_stage"] = "photo"
        return await update.message.reply_text(f"محصول #{row['id']} ثبت شد. عکس را بفرست (یا بنویس «بدون عکس»).")

    # --- edit product flow (admin) ---
    if ctx.user_data.get("edit_stage") == "ask_id" and is_admin(update):
        if not re.fullmatch(r"\d+", txt):
            return await update.message.reply_text("آیدی باید عدد باشد.")
        pid = int(txt)
        row = db_exec("SELECT id,name,price FROM products WHERE id=%s", (pid,), fetch="one")
        if not row:
            return await update.message.reply_text("محصول پیدا نشد.")
        ctx.user_data["edit_pid"] = pid
        ctx.user_data["edit_stage"] = "choose_field"
        return await update.message.reply_text("چه چیزی را تغییر بدهم؟ یکی از: نام / قیمت / عکس")

    if ctx.user_data.get("edit_stage") == "choose_field" and is_admin(update):
        fld = txt.strip()
        if fld not in {"نام", "قیمت", "عکس"}:
            return await update.message.reply_text("لطفاً یکی از این‌ها: نام / قیمت / عکس")
        ctx.user_data["edit_field"] = fld
        ctx.user_data["edit_stage"] = "await_value"
        if fld == "نام":
            return await update.message.reply_text("نام جدید:")
        if fld == "قیمت":
            return await update.message.reply_text("قیمت جدید (هزار تومان):")
        return await update.message.reply_text("عکس جدید را بفرست.")

    # مقدار متنی برای ویرایش (نام/قیمت)
    if ctx.user_data.get("edit_stage") == "await_value" and is_admin(update):
        pid = ctx.user_data.get("edit_pid")
        fld = ctx.user_data.get("edit_field")
        if fld == "نام":
            db_exec("UPDATE products SET name=%s WHERE id=%s", (txt, pid))
            ctx.user_data.clear()
            return await update.message.reply_text("نام محصول به‌روزرسانی شد ✅")
        if fld == "قیمت":
            if not re.fullmatch(r"\d+", txt):
                return await update.message.reply_text("فقط عدد قیمت را بفرست.")
            db_exec("UPDATE products SET price=%s WHERE id=%s", (int(txt), pid))
            ctx.user_data.clear()
            return await update.message.reply_text("قیمت محصول به‌روزرسانی شد ✅")

    # پنل ادمین
    if txt == "🧑‍💻 پنل ادمین":
        if not is_admin(update):
            return
        topups = db_exec("SELECT id,user_id,amount FROM topups WHERE status='pending' ORDER BY id ASC LIMIT 10", fetch="all")
        orders = db_exec("""
            SELECT o.id, u.user_id, p.name, o.deliver_method, o.status
            FROM orders o
            JOIN users u ON u.user_id=o.user_id
            JOIN products p ON p.id=o.product_id
            WHERE o.status IN ('pending','paid')
            ORDER BY o.id ASC
            LIMIT 10
        """, fetch="all")
        txta = "📊 *صف بررسی ادمین*\n\n"
        txta += "Topups:\n" + ("\n".join([f"#{t['id']} — user {t['user_id']} — {t['amount']} تومان" for t in topups]) or "—") + "\n\n"
        txta += "Orders:\n" + ("\n".join([f"#{o['id']} — {o['name']} — {o['deliver_method'] or '-'} — {o['status']}" for o in orders]) or "—")
        return await update.message.reply_text(txta, parse_mode="Markdown")

    # fallback
    return await update.message.reply_text("از دکمه‌ها استفاده کن 🙂", reply_markup=main_kb(is_admin(update)))

# ---------------- Photos (receipt/product photo) ----------------
async def photo_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id
    uid = update.effective_user.id

    # رسید شارژ کیف پول
    if ctx.user_data.get("await_topup_receipt"):
        amt = ctx.user_data.get("topup_amount", 0)
        row = db_exec(
            "INSERT INTO topups(user_id,amount,status,receipt_photo) VALUES (%s,%s,'pending',%s) RETURNING id",
            (uid, amt, file_id), fetch="one"
        )
        ctx.user_data.pop("await_topup_receipt", None)
        await update.message.reply_text("رسید دریافت شد ✅. پس از تأیید ادمین، کیف پولت شارژ می‌شود.")
        try:
            await ctx.bot.send_message(ADMIN_ID, f"درخواست شارژ #{row['id']} — user {uid} — مبلغ {amt}")
            await ctx.bot.send_photo(ADMIN_ID, file_id, caption=f"Topup #{row['id']}")
        except Exception:
            pass
        return

    # افزودن محصول — عکس
    if ctx.user_data.get("add_stage") == "photo" and is_admin(update):
        pid = ctx.user_data.get("new_product_id")
        db_exec("UPDATE products SET photo_id=%s WHERE id=%s", (file_id, pid))
        ctx.user_data.clear()
        return await update.message.reply_text("محصول با عکس ذخیره شد ✅")

    # ویرایش محصول — عکس
    if ctx.user_data.get("edit_stage") == "await_value" and ctx.user_data.get("edit_field") == "عکس" and is_admin(update):
        pid = ctx.user_data.get("edit_pid")
        db_exec("UPDATE products SET photo_id=%s WHERE id=%s", (file_id, pid))
        ctx.user_data.clear()
        return await update.message.reply_text("عکس محصول به‌روزرسانی شد ✅")

    # رسید سفارش (پس از انتخاب تحویل)
    if ctx.user_data.get("await_order_receipt"):
        oid = ctx.user_data.pop("await_order_receipt")
        db_exec("UPDATE orders SET receipt_photo=%s, status='paid' WHERE id=%s", (file_id, oid))
        await update.message.reply_text("رسید سفارش دریافت شد ✅. پس از تأیید ادمین اطلاع می‌دهیم.")
        try:
            await ctx.bot.send_message(ADMIN_ID, f"سفارش #{oid} پرداخت شد (در انتظار بررسی).")
            await ctx.bot.send_photo(ADMIN_ID, file_id, caption=f"Order #{oid}")
        except Exception:
            pass
        return

    await update.message.reply_text("این عکس در جریان فعالی استفاده نشد.")

# ---------------- Callback buttons: order + delivery ----------------
async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data.startswith("order:"):
        pid = int(data.split(":")[1])
        row = db_exec(
            "INSERT INTO orders(user_id,product_id,status) VALUES (%s,%s,'pending') RETURNING id",
            (q.from_user.id, pid), fetch="one"
        )
        oid = row["id"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ارسال به آدرس 🛵", callback_data=f"deliver:{oid}:delivery")],
            [InlineKeyboardButton("تحویل حضوری 🏠", callback_data=f"deliver:{oid}:pickup")],
        ])
        if q.message.photo:
            await q.edit_message_caption(
                caption=(q.message.caption or "") + f"\n\nسفارش #{oid} ایجاد شد. روش تحویل را انتخاب کن:",
                reply_markup=kb
            )
        else:
            await q.edit_message_text(
                text=(q.message.text or "") + f"\n\nسفارش #{oid} ایجاد شد. روش تحویل را انتخاب کن:",
                reply_markup=kb
            )
        return

    if data.startswith("deliver:"):
        _, oid, method = data.split(":")
        oid = int(oid)
        db_exec("UPDATE orders SET deliver_method=%s WHERE id=%s", (method, oid))
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(
            "روش تحویل ثبت شد ✅\nبرای نهایی‌کردن، مبلغ سفارش را کارت‌به‌کارت کنید و رسید را به صورت عکس ارسال کنید."
        )
        ctx.user_data["await_order_receipt"] = oid
        return

# ---------------- Admin commands ----------------
async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    topups = db_exec("SELECT id,user_id,amount,status FROM topups WHERE status='pending' ORDER BY id ASC LIMIT 10", fetch="all")
    orders = db_exec("""
        SELECT o.id, u.user_id, p.name, o.deliver_method, o.status
        FROM orders o
        JOIN users u ON u.user_id=o.user_id
        JOIN products p ON p.id=o.product_id
        WHERE o.status IN ('pending','paid')
        ORDER BY o.id ASC
        LIMIT 10
    """, fetch="all")
    txt = "📊 *صف بررسی ادمین*\n\n"
    txt += "Topups:\n" + ("\n".join([f"#{t['id']} — user {t['user_id']} — {t['amount']} — {t['status']}" for t in topups]) or "—") + "\n\n"
    txt += "Orders:\n" + ("\n".join([f"#{o['id']} — {o['name']} — {o['deliver_method'] or '-'} — {o['status']}" for o in orders]) or "—")
    await update.message.reply_text(txt, parse_mode="Markdown")

async def cmd_approve_topup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    parts = (update.message.text or "").split()
    if len(parts) < 2: return await update.message.reply_text("استفاده: /approve_topup <id>")
    tid = int(parts[1])
    row = db_exec("SELECT user_id,amount,status FROM topups WHERE id=%s", (tid,), fetch="one")
    if not row: return await update.message.reply_text("پیدا نشد.")
    if row["status"] != "pending": return await update.message.reply_text("این درخواست pending نیست.")
    db_exec("UPDATE topups SET status='approved' WHERE id=%s", (tid,))
    db_exec("UPDATE users SET wallet = wallet + %s WHERE user_id=%s", (row["amount"], row["user_id"]))
    await update.message.reply_text(f"Topup #{tid} تایید شد و {row['amount']} تومان شارژ شد.")
    try:
        await ctx.bot.send_message(row["user_id"], f"شارژ کیف پول شما ({row['amount']} تومان) تایید شد ✅")
    except Exception:
        pass

async def cmd_reject_topup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    parts = (update.message.text or "").split()
    if len(parts) < 2: return await update.message.reply_text("استفاده: /reject_topup <id>")
    tid = int(parts[1])
    db_exec("UPDATE topups SET status='rejected' WHERE id=%s", (tid,))
    await update.message.reply_text(f"Topup #{tid} رد شد.")

# ---------------- Utils ----------------
async def cmd_dbping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        row = db_exec("SELECT 1 AS ok", fetch="one")
        await update.message.reply_text("✅ DB OK" if row and row["ok"] == 1 else "❌ DB FAIL")
    except Exception as e:
        await update.message.reply_text(f"DB error: {e}")

# ---------------- App ----------------
def build_app() -> Application:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dbping", cmd_dbping))

    # admin commands
    app.add_handler(CommandHandler("panel", cmd_panel))
    app.add_handler(CommandHandler("approve_topup", cmd_approve_topup))
    app.add_handler(CommandHandler("reject_topup", cmd_reject_topup))

    app.add_handler(CallbackQueryHandler(cb_router))

    # photos
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))

    # texts
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))

    return app

if __name__ == "__main__":
    build_app().run_polling(drop_pending_updates=True)
