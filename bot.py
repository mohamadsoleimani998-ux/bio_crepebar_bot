import os
import io
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, Response
from typing import Tuple

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
import asyncio
import threading

# ================= ENV =================
BOT_TOKEN    = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "").strip()   # e.g. https://your-service.onrender.com
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))
PORT         = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in env")
if not WEBHOOK_URL or WEBHOOK_URL.startswith("http://"):
    raise RuntimeError("WEBHOOK_URL must be https base URL (no trailing /webhook)")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing in env")

# ================= LOG =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("bio-crepebar-bot")

# ================ DB ===================
def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def db_exec(sql: str, params: Tuple = ()):
    with db_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)

def db_q(sql: str, params: Tuple = ()):
    with db_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

def migrate():
    db_exec("""CREATE TABLE IF NOT EXISTS users(
        tg_id BIGINT PRIMARY KEY,
        name TEXT,
        phone TEXT,
        address TEXT,
        wallet BIGINT DEFAULT 0
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS products(
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price BIGINT NOT NULL,
        photo_file_id TEXT
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS cart(
        tg_id BIGINT NOT NULL,
        product_id INT NOT NULL,
        qty INT NOT NULL DEFAULT 1,
        PRIMARY KEY (tg_id, product_id),
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS orders(
        id SERIAL PRIMARY KEY,
        tg_id BIGINT NOT NULL,
        total BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', -- pending, awaiting_payment, paid, preparing, delivered, canceled
        delivery TEXT, -- courier/pickup
        name TEXT, phone TEXT, address TEXT,
        proof TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS order_items(
        id SERIAL PRIMARY KEY,
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        name TEXT, price BIGINT, qty INT,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS topups(
        id SERIAL PRIMARY KEY,
        tg_id BIGINT NOT NULL,
        amount BIGINT NOT NULL,
        ref TEXT,
        status TEXT NOT NULL DEFAULT 'waiting'
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS music(
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        file_id TEXT NOT NULL
    );""")
    log.info("DB migrations ensured.")

# ============== HELPERS =================
def ensure_user(tg_id: int, full_name: str):
    db_exec("INSERT INTO users(tg_id, name) VALUES(%s,%s) ON CONFLICT DO NOTHING;", (tg_id, full_name))

def is_admin(u) -> bool:
    return bool(ADMIN_ID and u and u.id == ADMIN_ID)

def fmt_price(v: int) -> str:
    return f"{v:,}".replace(",", "٬") + " تومان"

# ============ KEYBOARDS =================
def home_kb(admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("☕️ منوی محصولات", callback_data="menu")],
        [InlineKeyboardButton("🧺 سبد خرید", callback_data="cart")],
        [InlineKeyboardButton("🧾 ثبت سفارش", callback_data="checkout")],
        [InlineKeyboardButton("💸 کیف پول", callback_data="wallet")],
        [InlineKeyboardButton("🎵 موزیک‌های کافه", callback_data="music")],
        [InlineKeyboardButton("🎮 بازی (به‌زودی)", callback_data="game")],
        [InlineKeyboardButton("📱 اینستاگرام", url="https://instagram.com/bio.crepebar")]
    ]
    if admin:
        rows += [
            [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add")],
            [InlineKeyboardButton("✏️ مدیریت محصولات", callback_data="admin:manage")],
            [InlineKeyboardButton("📦 سفارش‌ها", callback_data="admin:orders")],
            [InlineKeyboardButton("🎵 افزودن موزیک", callback_data="admin:addmusic")],
            [InlineKeyboardButton("✅ تایید شارژها", callback_data="admin:topups")]
        ]
    return InlineKeyboardMarkup(rows)

def menu_item_kb(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"cart:add:{pid}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="menu")]
    ])

# =============== BOT LOGIC ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.full_name)
    await update.effective_message.reply_text(
        "به بایو کِرپ بار خوش اومدی ☕️",
        reply_markup=home_kb(is_admin(u))
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# -------- MENU ----------
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    rows = db_q("SELECT id,name,price FROM products ORDER BY id;")
    if not rows:
        text = "هنوز محصولی ثبت نشده."
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.effective_message.reply_text(text)
        return
    lines = [f"{r['id']}. {r['name']} — {fmt_price(r['price'])}" for r in rows]
    kb = [[InlineKeyboardButton(f"🔍 {r['name']}", callback_data=f"menu:item:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("🔙 خانه", callback_data="home")])
    if edit and update.callback_query:
        await update.callback_query.edit_message_text("منو:\n" + "\n".join(lines),
                                                     reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_message.reply_text("منو:\n" + "\n".join(lines),
                                                  reply_markup=InlineKeyboardMarkup(kb))

# -------- CART / CHECKOUT ----------
def create_order_from_cart(tg_id: int, delivery: str, as_awaiting: bool) -> int:
    items = db_q("""SELECT p.id,p.name,p.price,c.qty
                    FROM cart c JOIN products p ON p.id=c.product_id
                    WHERE c.tg_id=%s;""", (tg_id,))
    total = sum(i["price"] * i["qty"] for i in items)
    prof = db_q("SELECT name,phone,address FROM users WHERE tg_id=%s;", (tg_id,))[0]
    status = "awaiting_payment" if as_awaiting else "paid"
    row = db_q("""INSERT INTO orders(tg_id,total,status,delivery,name,phone,address)
                  VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id;""",
               (tg_id, total, status, delivery, prof["name"], prof["phone"], prof["address"]))
    oid = int(row[0]["id"])
    for i in items:
        db_exec("""INSERT INTO order_items(order_id,product_id,name,price,qty)
                   VALUES(%s,%s,%s,%s,%s);""", (oid, i["id"], i["name"], i["price"], i["qty"]))
    db_exec("DELETE FROM cart WHERE tg_id=%s;", (tg_id,))
    return oid

# -------- CALLBACKS ----------
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = update.effective_user
    data = q.data

    # خانه/بازگشت
    if data == "home":
        await q.edit_message_text("خانه:", reply_markup=home_kb(is_admin(u))); return

    # منو
    if data == "menu":
        await show_menu(update, context, edit=True); return

    if data.startswith("menu:item:"):
        pid = int(data.split(":")[-1])
        r = db_q("SELECT id,name,price,photo_file_id FROM products WHERE id=%s;", (pid,))
        if not r:
            await q.edit_message_text("یافت نشد."); return
        r = r[0]
        txt = f"«{r['name']}» — {fmt_price(r['price'])}"
        if r["photo_file_id"]:
            try:
                await q.edit_message_media(InputMediaPhoto(r["photo_file_id"], caption=txt))
                await q.edit_message_caption(caption=txt, reply_markup=menu_item_kb(pid))
            except Exception:
                await q.edit_message_text(txt, reply_markup=menu_item_kb(pid))
        else:
            await q.edit_message_text(txt, reply_markup=menu_item_kb(pid))
        return

    # سبد
    if data == "cart":
        items = db_q("""SELECT c.product_id p,p.name,p.price,c.qty
                        FROM cart c JOIN products p ON p.id=c.product_id
                        WHERE c.tg_id=%s ORDER BY p.id;""", (u.id,))
        if not items:
            await q.edit_message_text("سبد شما خالیه.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منو", callback_data="menu")],
                [InlineKeyboardButton("خانه", callback_data="home")]
            ])); return
        total = sum(i["price"] * i["qty"] for i in items)
        lines = [f"{i['name']} × {i['qty']} — {fmt_price(i['price']*i['qty'])}" for i in items]
        kb = []
        for i in items:
            kb.append([InlineKeyboardButton(f"➖ {i['name']}", callback_data=f"cart:dec:{i['p']}"),
                       InlineKeyboardButton("➕", callback_data=f"cart:inc:{i['p']}"),
                       InlineKeyboardButton("🗑", callback_data=f"cart:del:{i['p']}")])
        kb += [
            [InlineKeyboardButton("ادامه خرید", callback_data="menu")],
            [InlineKeyboardButton("تسویه و ثبت سفارش", callback_data="checkout")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ]
        await q.edit_message_text("سبد خرید:\n" + "\n".join(lines) + f"\n— جمع: {fmt_price(total)}",
                                  reply_markup=InlineKeyboardMarkup(kb)); return

    if data.startswith("cart:add:"):
        pid = int(data.split(":")[-1])
        db_exec("""INSERT INTO cart(tg_id,product_id,qty) VALUES(%s,%s,1)
                   ON CONFLICT (tg_id,product_id) DO UPDATE SET qty=cart.qty+1;""", (u.id, pid))
        await q.edit_message_text("به سبد اضافه شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧺 سبد خرید", callback_data="cart")],
            [InlineKeyboardButton("منو", callback_data="menu")]
        ])); return
    if data.startswith("cart:inc:"):
        pid = int(data.split(":")[-1])
        db_exec("UPDATE cart SET qty=qty+1 WHERE tg_id=%s AND product_id=%s;", (u.id, pid))
        await cb(update, context); return
    if data.startswith("cart:dec:"):
        pid = int(data.split(":")[-1])
        db_exec("UPDATE cart SET qty=GREATEST(qty-1,1) WHERE tg_id=%s AND product_id=%s;", (u.id, pid))
        await cb(update, context); return
    if data.startswith("cart:del:"):
        pid = int(data.split(":")[-1])
        db_exec("DELETE FROM cart WHERE tg_id=%s AND product_id=%s;", (u.id, pid))
        await cb(update, context); return

    # تسویه/چک‌اوت
    if data == "checkout":
        items = db_q("""SELECT p.id,p.name,p.price,c.qty
                        FROM cart c JOIN products p ON p.id=c.product_id
                        WHERE c.tg_id=%s;""", (u.id,))
        if not items:
            await q.edit_message_text("سبد خالیه.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منو", callback_data="menu")],
                [InlineKeyboardButton("خانه", callback_data="home")]
            ])); return
        total = sum(i["price"] * i["qty"] for i in items)
        prof = db_q("SELECT name,phone,address FROM users WHERE tg_id=%s;", (u.id,))[0]
        if not prof["name"] or not prof["phone"] or not prof["address"]:
            context.user_data["profile_step"] = "name"
            await q.edit_message_text("برای ثبت سفارش، اطلاعاتت رو کامل کن.\nنام و نام‌خانوادگی را ارسال کن:")
            return
        context.user_data["pending_total"] = total
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 ارسال با پیک", callback_data="dlv:courier")],
            [InlineKeyboardButton("🤝 تحویل حضوری", callback_data="dlv:pickup")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])
        await q.edit_message_text(f"جمع سبد: {fmt_price(total)}\nروش تحویل را انتخاب کن:", reply_markup=kb)
        return

    if data.startswith("dlv:"):
        method = "courier" if data.endswith("courier") else "pickup"
        context.user_data["delivery_method"] = method
        total = int(context.user_data.get("pending_total", 0))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("پرداخت از کیف پول", callback_data="pay:wallet")],
            [InlineKeyboardButton("کارت به کارت", callback_data="pay:bank")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])
        await q.edit_message_text(f"مبلغ قابل پرداخت: {fmt_price(total)}", reply_markup=kb)
        return

    if data == "pay:wallet":
        total = int(context.user_data.get("pending_total", 0))
        bal = int((db_q("SELECT wallet FROM users WHERE tg_id=%s;", (u.id,)) or [{"wallet": 0}])[0]["wallet"] or 0)
        if bal < total:
            await q.edit_message_text(
                f"موجودی کافی نیست. کمبود: {fmt_price(total - bal)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💸 کیف پول", callback_data="wallet")],
                    [InlineKeyboardButton("کارت به کارت", callback_data="pay:bank")],
                    [InlineKeyboardButton("خانه", callback_data="home")]
                ])
            ); return
        oid = create_order_from_cart(u.id, context.user_data.get("delivery_method", "courier"), as_awaiting=False)
        db_exec("UPDATE users SET wallet=wallet-%s WHERE tg_id=%s;", (total, u.id))
        await q.edit_message_text(f"سفارش #{oid} پرداخت و ثبت شد ✅",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("خانه", callback_data="home")]]))
        return

    if data == "pay:bank":
        oid = create_order_from_cart(u.id, context.user_data.get("delivery_method", "courier"), as_awaiting=True)
        context.user_data["await_bank_proof"] = oid
        await q.edit_message_text(
            f"سفارش #{oid} ثبت شد (در انتظار پرداخت).\n"
            "مبلغ را کارت‌به‌کارت کن و «رسید یا ۴ رقم آخر کارت» را بفرست:\n"
            "💳 6037-xxxx-xxxx-xxxx بنام Bio Crepe Bar"
        ); return

    # کیف پول
    if data == "wallet":
        bal = int((db_q("SELECT wallet FROM users WHERE tg_id=%s;", (u.id,)) or [{"wallet": 0}])[0]["wallet"] or 0)
        await q.edit_message_text(f"موجودی: {fmt_price(bal)}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ شارژ کارت‌به‌کارت", callback_data="wallet:topup")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])); return
    if data == "wallet:topup":
        context.user_data["await_topup_amount"] = True
        await q.edit_message_text("مبلغ شارژ (عدد به تومان) را بفرست:"); return

    # موزیک
    if data == "music":
        rows = db_q("SELECT id,title FROM music ORDER BY id DESC LIMIT 20;")
        if not rows:
            await q.edit_message_text("فعلاً موزیکی نیست.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("خانه", callback_data="home")]
            ])); return
        kb = [[InlineKeyboardButton(f"▶️ {r['title']}", callback_data=f"music:play:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("خانه", callback_data="home")])
        await q.edit_message_text("🎵 موزیک‌ها:", reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("music:play:"):
        mid = int(data.split(":")[-1])
        r = db_q("SELECT title,file_id FROM music WHERE id=%s;", (mid,))
        if not r: await q.edit_message_text("یافت نشد."); return
        await q.edit_message_text(f"🎵 {r[0]['title']}"); await q.message.chat.send_audio(audio=r[0]["file_id"]); return

    # بازی
    if data == "game":
        await q.edit_message_text("🎮 به‌زودی!", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])); return

    # ADMIN: محصولات
    if data == "admin:add":
        if not is_admin(u): return
        context.user_data["add_step"] = "name"
        await q.edit_message_text("نام محصول را بفرست:"); return

    if data == "admin:manage":
        if not is_admin(u): return
        rows = db_q("SELECT id,name,price FROM products ORDER BY id;")
        if not rows: await q.edit_message_text("محصولی نیست."); return
        kb = [[InlineKeyboardButton(f"{r['id']}. {r['name']} ({fmt_price(r['price'])})",
                                    callback_data=f"admin:edit:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("خانه", callback_data="home")])
        await q.edit_message_text("مدیریت محصولات:", reply_markup=InlineKeyboardMarkup(kb)); return

    if data.startswith("admin:edit:"):
        if not is_admin(u): return
        pid = int(data.split(":")[-1])
        r = db_q("SELECT id,name,price FROM products WHERE id=%s;", (pid,))
        if not r: await q.edit_message_text("یافت نشد."); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ نام", callback_data=f"admin:ename:{pid}")],
            [InlineKeyboardButton("💲 قیمت", callback_data=f"admin:eprice:{pid}")],
            [InlineKeyboardButton("🖼 عکس", callback_data=f"admin:ephoto:{pid}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"admin:del:{pid}")],
            [InlineKeyboardButton("بازگشت", callback_data="admin:manage")]
        ])
        await q.edit_message_text(f"ویرایش «{r[0]['name']}»", reply_markup=kb); return

    if data.startswith("admin:del:"):
        if not is_admin(u): return
        pid = int(data.split(":")[-1])
        db_exec("DELETE FROM products WHERE id=%s;", (pid,))
        await q.edit_message_text("حذف شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("مدیریت", callback_data="admin:manage")]
        ])); return

    if data.startswith("admin:ename:"):
        if not is_admin(u): return
        context.user_data["edit_step"] = ("name", int(data.split(":")[-1]))
        await q.edit_message_text("نام جدید را بفرست:"); return
    if data.startswith("admin:eprice:"):
        if not is_admin(u): return
        context.user_data["edit_step"] = ("price", int(data.split(":")[-1]))
        await q.edit_message_text("قیمت جدید (عدد) را بفرست:"); return
    if data.startswith("admin:ephoto:"):
        if not is_admin(u): return
        context.user_data["edit_step"] = ("photo", int(data.split(":")[-1]))
        await q.edit_message_text("عکس جدید را بفرست:"); return

    # ADMIN: سفارش‌ها
    if data == "admin:orders":
        if not is_admin(u): return
        rows = db_q("SELECT id,tg_id,total,status FROM orders ORDER BY id DESC LIMIT 20;")
        if not rows: await q.edit_message_text("سفارشی نیست."); return
        kb = [[InlineKeyboardButton(f"#{r['id']} — {r['status']} — {fmt_price(r['total'])}",
                                    callback_data=f"admin:order:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("خانه", callback_data="home")])
        await q.edit_message_text("سفارش‌ها:", reply_markup=InlineKeyboardMarkup(kb)); return

    if data.startswith("admin:order:"):
        if not is_admin(u): return
        oid = int(data.split(":")[-1])
        o = db_q("SELECT * FROM orders WHERE id=%s;", (oid,))
        if not o: await q.edit_message_text("یافت نشد."); return
        o = o[0]
        txt = (f"Order #{o['id']} — {o['status']}\n"
               f"User: {o['tg_id']}\nTotal: {fmt_price(o['total'])}\n"
               f"Delivery: {o['delivery']}\nProof: {o.get('proof') or '-'}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ paid", callback_data=f"admin:ost:{oid}:paid"),
             InlineKeyboardButton("🧑‍🍳 preparing", callback_data=f"admin:ost:{oid}:preparing")],
            [InlineKeyboardButton("📦 delivered", callback_data=f"admin:ost:{oid}:delivered"),
             InlineKeyboardButton("❌ canceled", callback_data=f"admin:ost:{oid}:canceled")],
            [InlineKeyboardButton("⬅️ لیست", callback_data="admin:orders")]
        ])
        await q.edit_message_text(txt, reply_markup=kb); return

    if data.startswith("admin:ost:"):
        if not is_admin(u): return
        _, _, oid, st = data.split(":")
        db_exec("UPDATE orders SET status=%s WHERE id=%s;", (st, int(oid)))
        await q.edit_message_text("به‌روزرسانی شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ لیست سفارش‌ها", callback_data="admin:orders")]
        ])); return

    # ADMIN: شارژها
    if data == "admin:topups":
        if not is_admin(u): return
        rows = db_q("SELECT id,tg_id,amount,ref FROM topups WHERE status='waiting' ORDER BY id;")
        if not rows:
            await q.edit_message_text("درخواستی در انتظار تایید نیست."); return
        kb = [[InlineKeyboardButton(
            f"کاربر {r['tg_id']} — {fmt_price(r['amount'])} — ref:{r['ref']}",
            callback_data=f"admin:topup:{r['id']}")] for r in rows]
        await q.edit_message_text("لیست شارژها:", reply_markup=InlineKeyboardMarkup(kb)); return

    if data.startswith("admin:topup:"):
        if not is_admin(u): return
        tid = int(data.split(":")[-1])
        r = db_q("SELECT id,tg_id,amount FROM topups WHERE id=%s AND status='waiting';", (tid,))
        if not r: await q.edit_message_text("یافت نشد."); return
        r = r[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید", callback_data=f"admin:topupok:{tid}")],
            [InlineKeyboardButton("❌ رد",   callback_data=f"admin:topupno:{tid}")],
            [InlineKeyboardButton("⬅️ لیست", callback_data="admin:topups")]
        ])
        await q.edit_message_text(
            f"تایید شارژ کاربر {r['tg_id']} به مبلغ {fmt_price(r['amount'])} ؟", reply_markup=kb
        ); return

    if data.startswith("admin:topupok:"):
        if not is_admin(u): return
        tid = int(data.split(":")[-1])
        r = db_q("SELECT tg_id,amount FROM topups WHERE id=%s AND status='waiting';", (tid,))
        if not r: await q.edit_message_text("یافت نشد."); return
        tg_id, amount = r[0]["tg_id"], int(r[0]["amount"])
        db_exec("UPDATE users SET wallet=wallet+%s WHERE tg_id=%s;", (amount, tg_id))
        db_exec("UPDATE topups SET status='approved' WHERE id=%s;", (tid,))
        await q.edit_message_text("تایید شد ✅"); return

    if data.startswith("admin:topupno:"):
        if not is_admin(u): return
        tid = int(data.split(":")[-1])
        db_exec("UPDATE topups SET status='rejected' WHERE id=%s;", (tid,))
        await q.edit_message_text("رد شد."); return

# -------- TEXT & MEDIA ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.full_name)
    t = (update.message.text or "").strip()

    # پروفایل برای checkout
    p = context.user_data.get("profile_step")
    if p == "name":
        db_exec("UPDATE users SET name=%s WHERE tg_id=%s;", (t, u.id))
        context.user_data["profile_step"] = "phone"
        await update.message.reply_text("شماره موبایل را بفرست:"); return
    if p == "phone":
        db_exec("UPDATE users SET phone=%s WHERE tg_id=%s;", (t, u.id))
        context.user_data["profile_step"] = "address"
        await update.message.reply_text("آدرس کامل را بفرست:"); return
    if p == "address":
        db_exec("UPDATE users SET address=%s WHERE tg_id=%s;", (t, u.id))
        context.user_data.pop("profile_step", None)
        await update.message.reply_text("ذخیره شد ✅ دوباره «ثبت سفارش» را بزن."); return

    # شارژ کیف پول
    if context.user_data.pop("await_topup_amount", False):
        if not t.isdigit():
            await update.message.reply_text("عدد نامعتبر."); return
        amt = int(t)
        context.user_data["await_topup_ref"] = amt
        await update.message.reply_text(
            f"{fmt_price(amt)} را کارت‌به‌کارت کن و «رسید/۴ رقم آخر کارت» را بفرست:"
        ); return
    if "await_topup_ref" in context.user_data:
        amt = int(context.user_data.pop("await_topup_ref"))
        db_exec("INSERT INTO topups(tg_id,amount,ref) VALUES(%s,%s,%s);", (u.id, amt, t))
        await update.message.reply_text("درخواست شارژ ثبت شد ✅ پس از تایید ادمین اعمال می‌شود.")
        if ADMIN_ID:
            try:
                await context.bot.send_message(ADMIN_ID, f"Topup: user {u.id} - {fmt_price(amt)} - ref:{t}")
            except Exception:
                pass
        return

    # رسید کارت‌به‌کارت برای سفارش
    if "await_bank_proof" in context.user_data:
        oid = int(context.user_data.pop("await_bank_proof"))
        db_exec("UPDATE orders SET proof=%s WHERE id=%s;", (t, oid))
        await update.message.reply_text(f"رسید دریافت شد ✅ سفارش #{oid} در انتظار تایید ادمین است.")
        if ADMIN_ID:
            try:
                await context.bot.send_message(ADMIN_ID, f"Order #{oid} proof by {u.id}: {t}")
            except Exception:
                pass
        return

    # افزودن محصول (ادمین): نام/قیمت
    if is_admin(u) and context.user_data.get("add_step") == "name":
        context.user_data["new_name"] = t
        context.user_data["add_step"] = "price"
        await update.message.reply_text("قیمت (عدد) را بفرست:"); return
    if is_admin(u) and context.user_data.get("add_step") == "price":
        if not t.replace(",", "").isdigit():
            await update.message.reply_text("قیمت نامعتبر."); return
        context.user_data["new_price"] = int(t.replace(",", ""))
        context.user_data["add_step"] = "photo_or_done"
        await update.message.reply_text("اگر عکس داری الان بفرست؛ وگرنه /done را بزن."); return

    # ویرایش محصول (ادمین): نام/قیمت
    if is_admin(u) and context.user_data.get("edit_step"):
        kind, pid = context.user_data["edit_step"]
        if kind == "name":
            db_exec("UPDATE products SET name=%s WHERE id=%s;", (t, pid))
            context.user_data.pop("edit_step", None)
            await update.message.reply_text("نام به‌روزرسانی شد ✅"); return
        if kind == "price":
            if not t.replace(",", "").isdigit():
                await update.message.reply_text("قیمت نامعتبر."); return
            db_exec("UPDATE products SET price=%s WHERE id=%s;", (int(t.replace(",", "")), pid))
            context.user_data.pop("edit_step", None)
            await update.message.reply_text("قیمت به‌روزرسانی شد ✅"); return

    # افزودن موزیک: عنوان
    if is_admin(u) and context.user_data.get("music_step") == "title":
        context.user_data["music_title"] = t
        context.user_data["music_step"] = "file"
        await update.message.reply_text("فایل موزیک را به‌صورت Audio بفرست."); return

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    # افزودن محصول: عکس
    if is_admin(u) and context.user_data.get("add_step") == "photo_or_done":
        context.user_data["new_photo"] = update.message.photo[-1].file_id
        await update.message.reply_text("عکس ذخیره شد. /done را بزن.")
        return
    # ویرایش عکس
    if is_admin(u) and context.user_data.get("edit_step"):
        kind, pid = context.user_data["edit_step"]
        if kind == "photo":
            fid = update.message.photo[-1].file_id
            db_exec("UPDATE products SET photo_file_id=%s WHERE id=%s;", (fid, pid))
            context.user_data.pop("edit_step", None)
            await update.message.reply_text("عکس به‌روزرسانی شد ✅")

async def audio_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if is_admin(u) and context.user_data.get("music_step") == "file":
        fid = update.message.audio.file_id
        title = context.user_data.pop("music_title", "Untitled")
        context.user_data.pop("music_step", None)
        db_exec("INSERT INTO music(title,file_id) VALUES(%s,%s);", (title, fid))
        await update.message.reply_text("موزیک ذخیره شد ✅")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_admin(u):
        return
    if context.user_data.get("add_step") != "photo_or_done":
        await update.message.reply_text("جریان افزودن فعال نیست."); return
    name  = context.user_data.pop("new_name", None)
    price = context.user_data.pop("new_price", None)
    photo = context.user_data.pop("new_photo", None)
    context.user_data.pop("add_step", None)
    if not name or price is None:
        await update.message.reply_text("نام/قیمت ناقص است."); return
    db_exec("INSERT INTO products(name,price,photo_file_id) VALUES(%s,%s,%s);", (name, price, photo))
    await update.message.reply_text("محصول ثبت شد ✅")

# ============== BUILD APP =================
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.AUDIO, audio_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    return app

# ============== FLASK + WEBHOOK ============
flask_app = Flask(__name__)
application: Application = None
_loop = asyncio.new_event_loop()

@flask_app.get("/")
def root():
    return "OK", 200

@flask_app.post("/webhook")
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return Response(status=400)
    update = Update.de_json(data, application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), _loop)
    return Response(status=200)

def start_telegram():
    global application
    migrate()
    asyncio.set_event_loop(_loop)
    application = build_app()

    async def _init():
        await application.initialize()
        await application.start()
        # حذف وبهوک قبلی و ست جدید
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            log.warning(f"delete_webhook warn: {e}")
        await application.bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
        log.info("Webhook set to %s/webhook", WEBHOOK_URL.rstrip("/"))

    _loop.run_until_complete(_init())
    threading.Thread(target=_loop.run_forever, daemon=True).start()

# هنگام import توسط Gunicorn اجرا می‌شود
start_telegram()

# این نام باید با Procfile هماهنگ باشد: web: gunicorn bot:app
app = flask_app
