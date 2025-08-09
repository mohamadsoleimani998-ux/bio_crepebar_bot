import os
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, filters
)

import psycopg
from psycopg.rows import dict_row

# ---------- Config ----------
BOT_TOKEN      = os.environ["BOT_TOKEN"]                          
DATABASE_URL   = os.environ["DATABASE_URL"]                       
WEBHOOK_URL    = os.environ["WEBHOOK_URL"].rstrip("/")            
ADMIN_IDS      = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.strip().isdigit()}
CASHBACK_PCT   = int(os.getenv("CASHBACK_PERCENT", "3"))
PORT           = int(os.getenv("PORT", "10000"))                  
WEBHOOK_PATH   = f"/webhook/{BOT_TOKEN}"                          

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar-bot")

# ---------- DB helpers ----------
def db_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)

def init_db():
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        tg_id       BIGINT PRIMARY KEY,
        username    TEXT,
        first_name  TEXT,
        last_name   TEXT,
        joined_at   TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS messages (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tg_id       BIGINT REFERENCES users(tg_id) ON DELETE CASCADE,
        text        TEXT,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );
    """
    with db_conn() as conn:
        conn.execute(sql)
    log.info("DB is ready.")

def upsert_user(u):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (tg_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tg_id) DO UPDATE SET
              username = EXCLUDED.username,
              first_name = EXCLUDED.first_name,
              last_name = EXCLUDED.last_name
            """,
            (u.id, u.username, u.first_name, u.last_name),
        )

def save_msg(user_id: int, text: str):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO messages (tg_id, text) VALUES (%s, %s)",
            (user_id, text),
        )

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("منو", callback_data="menu")],
        [InlineKeyboardButton("راهنما", callback_data="help")],
    ])
    msg = (
        f"سلام {user.first_name} 👋\n"
        f"به کِرِپ بار خوش اومدی!\n"
        f"کش‌بک فعلی: {CASHBACK_PCT}%\n"
        f"برای شروع از دکمه‌های زیر استفاده کن:"
    )
    await update.effective_chat.send_message(msg, reply_markup=kb)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "دستورات:\n"
        "/start - شروع و ثبت نام\n"
        "/help - راهنما\n"
        "/id - نمایش شناسه شما\n"
    )
    await update.effective_chat.send_message(text)

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(f"🆔 ID شما: `{update.effective_user.id}`", parse_mode="Markdown")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "menu":
        await q.edit_message_text(
            "منوی ساده:\n- سفارش حضوری\n- سفارش آنلاین (به‌زودی)\n- موجودی/کش‌بک (به‌زودی)"
        )
    elif q.data == "help":
        await q.edit_message_text(
            "هر سوالی داشتی همین‌جا بپرس 🌟"
        )

async def echo_and_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    txt = (update.message.text or "").strip()
    if txt:
        save_msg(user.id, txt)
    await update.message.reply_text("پیامت ثبت شد ✅")

# --- Admin broadcast ---
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("مثال: /broadcast سلام به همه")
        return

    text = " ".join(context.args)
    sent = 0
    with db_conn() as conn:
        rows = conn.execute("SELECT tg_id FROM users ORDER BY joined_at DESC LIMIT 1000").fetchall()
    for r in rows:
        try:
            await context.bot.send_message(r["tg_id"], text)
            sent += 1
        except Exception as e:
            log.warning("broadcast to %s failed: %s", r["tg_id"], e)
    await update.message.reply_text(f"ارسال شد برای {sent} نفر.")

# ---------- Main ----------
def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast))

    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_and_log))

    url_path = WEBHOOK_PATH
    full_webhook = f"{WEBHOOK_URL}{url_path}"

    log.info("Starting webhook on port %s, path=%s", PORT, url_path)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=full_webhook,
        drop_pending_updates=True,
        stop_signals=None,
    )

if __name__ == "__main__":
    main()
