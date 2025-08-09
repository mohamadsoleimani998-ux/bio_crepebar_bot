import os
import asyncio
import logging
from typing import Optional, Tuple

import psycopg2
import psycopg2.extras
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bio-crepebar-bot")

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is required")

WEBHOOK_BASE = (os.getenv("WEBHOOK_BASE") or os.getenv("WEBHOOK_URL") or "").rstrip("/")
if not WEBHOOK_BASE:
    raise RuntimeError("WEBHOOK_BASE (e.g. https://bio_crepebar_bot.onrender.com) env is required")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # اختیاری ولی بهتره بگذاری
PORT = int(os.getenv("PORT", "8000"))

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower())
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is required (Neon)")

# sslmode=require را اگر در DSN نیست اضافه می‌کنیم
if "sslmode" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL + ("&sslmode=require" if "?" in DATABASE_URL else "?sslmode=require")

ADMIN_IDS = {
    int(x) for x in (os.getenv("ADMIN_IDS") or "").replace(" ", "").split(",") if x.strip().isdigit()
}
CASHBACK_PERCENT = float(os.getenv("CASHBACK_PERCENT") or 3)  # پیش‌فرض 3 درصد


# ---------- DB helpers ----------
def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)


def run_migrations():
    """ایجاد جدول‌ها اگر وجود ندارند (idempotent)."""
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        first_name TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        cashback_total INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount INTEGER NOT NULL,
        cashback_awarded INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    log.info("DB migrations applied ✅")


def upsert_user(tg_id: int, username: Optional[str], first_name: Optional[str]) -> int:
    """کاربر را بساز/آپدیت کن و id برگردان."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (tg_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name
            RETURNING id;
            """,
            (tg_id, username, first_name),
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        return user_id


def add_purchase_for_tg(tg_id: int, amount: int) -> Tuple[int, int]:
    """برای کاربر با tg_id خرید ثبت می‌کند. (amount به تومان/عدد صحیح)"""
    cashback = round(amount * CASHBACK_PERCENT / 100.0)
    with db_conn() as conn, conn.cursor() as cur:
        # اطمینان از وجود کاربر
        cur.execute("SELECT id FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("کاربر در دیتابیس پیدا نشد")

        user_id = row[0]
        # ثبت خرید
        cur.execute(
            "INSERT INTO purchases (user_id, amount, cashback_awarded) VALUES (%s, %s, %s) RETURNING id;",
            (user_id, amount, cashback),
        )
        # به‌روزکردن کیف‌پول
        cur.execute(
            "UPDATE users SET cashback_total = cashback_total + %s WHERE id=%s;",
            (cashback, user_id),
        )
        conn.commit()
    return amount, cashback


def get_user_summary(tg_id: int) -> Tuple[int, int]:
    """cashback_total و تعداد خریدها را برمی‌گرداند."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, cashback_total FROM users WHERE tg_id=%s", (tg_id,))
        u = cur.fetchone()
        if not u:
            return 0, 0
        user_id, cashback_total = u["id"], int(u["cashback_total"])
        cur.execute("SELECT COUNT(*) FROM purchases WHERE user_id=%s", (user_id,))
        count = int(cur.fetchone()[0])
        return cashback_total, count


# ---------- Handlers ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username, u.first_name)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 حساب من", callback_data="me")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
    ])
    await update.message.reply_text(
        "سلام! ربات بایو کِرِپ بار فعاله ✅\n"
        "از دکمه‌ها استفاده کن.",
        reply_markup=kb,
    )


async def cb_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "me":
        cash, cnt = get_user_summary(q.from_user.id)
        await q.edit_message_text(f"👤 وضعیت شما:\n"
                                  f"تعداد خرید: {cnt}\n"
                                  f"کیف‌پول کَش‌بَک: {cash} تومان")
    elif q.data == "help":
        await q.edit_message_text(
            "دستورها:\n"
            "/start — شروع و ثبت شما\n"
            "/me — وضعیت من\n"
            "/help — راهنما\n\n"
            "مدیر:\n"
            "/add_purchase <tg_id> <amount>\n"
            "/stats — آمار"
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cb_buttons(update, context)  # همان متن راهنما


async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cash, cnt = get_user_summary(update.effective_user.id)
    await update.message.reply_text(f"👤 وضعیت شما:\n"
                                    f"تعداد خرید: {cnt}\n"
                                    f"کیف‌پول کَش‌بَک: {cash} تومان")


async def add_purchase_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیر: /add_purchase <tg_id> <amount>"""
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔️ دسترسی مدیر لازم است.")
        return

    if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.message.reply_text("فرمت درست: /add_purchase <tg_id> <amount>")
        return

    tg_id = int(context.args[0])
    amount = int(context.args[1])
    try:
        add_amount, cashback = add_purchase_for_tg(tg_id, amount)
        await update.message.reply_text(
            f"✅ خرید ثبت شد.\n"
            f"کاربر: {tg_id}\nمبلغ: {add_amount} تومان\nکَش‌بَک افزوده‌شده: {cashback} تومان"
        )
    except ValueError:
        await update.message.reply_text("❗️کاربر در دیتابیس پیدا نشد.")
    except Exception as e:
        log.exception("add_purchase failed")
        await update.message.reply_text(f"خطا: {e}")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ دسترسی مدیر لازم است.")
        return
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users;")
        users = int(cur.fetchone()[0])
        cur.execute("SELECT COALESCE(SUM(amount),0), COALESCE(SUM(cashback_awarded),0) FROM purchases;")
        total_amount, total_cashback = map(int, cur.fetchone())
    await update.message.reply_text(
        f"📊 آمار:\nکاربران: {users}\n"
        f"مجموع خریدها: {total_amount} تومان\n"
        f"مجموع کش‌بک پرداخت‌شده: {total_cashback} تومان"
    )


# ---------- Main (Webhook) ----------
def main():
    run_migrations()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("me", me_cmd))
    application.add_handler(CommandHandler("add_purchase", add_purchase_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(  # دکمه‌های اینلاین
        # استفاده از همان تابع برای نمایش راهنما/حساب من
        # (CallbackQueryHandler را از طریق pattern ساده حذف کردیم، PTB خودش تشخیص می‌دهد)
        type("CBH", (), {"check_update": lambda *_: False})()  # placeholder: PTB نیاز ندارد
    )
    # راه درست CallbackQueryHandler:
    from telegram.ext import CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(cb_buttons))

    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{WEBHOOK_BASE}/{url_path}"

    log.info("Starting webhook on 0.0.0.0:%s path=%s", PORT, url_path)
    # نکته: از run_webhook استفاده می‌کنیم تا حلقه‌ی رویداد مدیریت شود و
    # خطاهای 'Cannot close a running event loop' رخ ندهد.
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
