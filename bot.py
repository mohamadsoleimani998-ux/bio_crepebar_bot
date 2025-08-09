import os, io
from typing import List
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ====== ENV ======
BOT_TOKEN    = os.getenv("BOT_TOKEN")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL")  # https, e.g. https://xxx.onrender.com/webhook
PORT         = int(os.getenv("PORT", "10000"))
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN missing")
if not WEBHOOK_URL or WEBHOOK_URL.startswith("http://"):
    raise RuntimeError("WEBHOOK_URL must be https")
if not DATABASE_URL: raise RuntimeError("DATABASE_URL missing")

# ====== DB ======
def conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def db_exec(sql:str, params:tuple=()):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)

def db_q(sql:str, params:tuple=()):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params); return cur.fetchall()

def migrate():
    db_exec("""CREATE TABLE IF NOT EXISTS users(
        tg_id BIGINT PRIMARY KEY,
        name TEXT, phone TEXT, address TEXT,
        wallet BIGINT DEFAULT 0
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS products(
        id SERIAL PRIMARY KEY, name TEXT NOT NULL, price BIGINT NOT NULL, photo_file_id TEXT
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS cart(
        tg_id BIGINT NOT NULL, product_id INT NOT NULL, qty INT NOT NULL DEFAULT 1,
        PRIMARY KEY(tg_id,product_id),
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS orders(
        id SERIAL PRIMARY KEY,
        tg_id BIGINT NOT NULL,
        total BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', -- pending, awaiting_payment, paid, preparing, delivered, canceled
        delivery TEXT, -- courier/pickup
        name TEXT, phone TEXT, address TEXT,
        proof TEXT, -- توضیح/رسید کارت‌به‌کارت
        created_at TIMESTAMP DEFAULT NOW()
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS order_items(
        id SERIAL PRIMARY KEY, order_id INT NOT NULL,
        product_id INT NOT NULL, name TEXT, price BIGINT, qty INT,
        FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS topups(
        id SERIAL PRIMARY KEY, tg_id BIGINT NOT NULL, amount BIGINT NOT NULL,
        ref TEXT, status TEXT NOT NULL DEFAULT 'waiting'
    );""")
    db_exec("""CREATE TABLE IF NOT EXISTS music(
        id SERIAL PRIMARY KEY, title TEXT NOT NULL, file_id TEXT NOT NULL
    );""")

# ====== UTILS ======
def ensure_user(u): db_exec("INSERT INTO users(tg_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING;", (u.id,u.full_name))
def is_admin(u):    return bool(ADMIN_ID and u and u.id==ADMIN_ID)
def fmt_price(v:int): return f"{v:,}".replace(",", "٬") + " تومان"
def wallet(tg):  return int((db_q("SELECT wallet FROM users WHERE tg_id=%s;",(tg,)) or [{"wallet":0}])[0]["wallet"] or 0)
def set_wallet(tg,amount): db_exec("""INSERT INTO users(tg_id,wallet) VALUES(%s,%s)
                                      ON CONFLICT (tg_id) DO UPDATE SET wallet=EXCLUDED.wallet;""",(tg,amount))

# ====== KBs ======
def home_kb(admin:bool):
    rows = [
        [InlineKeyboardButton("☕️ منوی محصولات", callback_data="menu")],
        [InlineKeyboardButton("🧺 سبد خرید", callback_data="cart")],
        [InlineKeyboardButton("🧾 ثبت سفارش", callback_data="checkout")],
        [InlineKeyboardButton("💸 کیف پول", callback_data="wallet")],
        [InlineKeyboardButton("🎵 موزیک‌های کافه", callback_data="music")],
        [InlineKeyboardButton("🎮 بازی (به‌زودی)", callback_data="game")],
        [InlineKeyboardButton("📱 اینستاگرام", url="https://instagram.com/your_page")]
    ]
    if admin:
        rows += [
            [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add")],
            [InlineKeyboardButton("✏️ مدیریت محصولات", callback_data="admin:manage")],
            [InlineKeyboardButton("📦 سفارش‌ها", callback_data="admin:orders")],
            [InlineKeyboardButton("🎵 افزودن موزیک", callback_data="admin:addmusic")]
        ]
    return InlineKeyboardMarkup(rows)

def menu_item_kb(pid:int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"cart:add:{pid}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="menu")]
    ])

# ====== START ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; ensure_user(u)
    await update.effective_message.reply_text("به بایو کِرپ بار خوش اومدی ☕️",
                                              reply_markup=home_kb(is_admin(u)))

# ====== MENU ======
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    rows = db_q("SELECT id,name,price FROM products ORDER BY id;")
    if not rows:
        t = "هنوز محصولی ثبت نشده."
        (await update.callback_query.edit_message_text(t)) if edit else await update.effective_message.reply_text(t)
        return
    lines = [f"{r['id']}. {r['name']} — {fmt_price(r['price'])}" for r in rows]
    kb = [[InlineKeyboardButton(f"🔍 {r['name']}", callback_data=f"menu:item:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("🔙 خانه", callback_data="home")])
    if edit:
        await update.callback_query.edit_message_text("منو:\n"+"\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_message.reply_text("منو:\n"+"\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

# ====== ORDER HELPERS ======
def create_order_from_cart(tg_id:int, delivery:str, as_awaiting:bool)->int:
    items = db_q("""SELECT p.id,p.name,p.price,c.qty FROM cart c JOIN products p ON p.id=c.product_id
                    WHERE c.tg_id=%s;""",(tg_id,))
    total = sum(i["price"]*i["qty"] for i in items)
    prof = db_q("SELECT name,phone,address FROM users WHERE tg_id=%s;", (tg_id,))[0]
    status = "awaiting_payment" if as_awaiting else "paid"
    row = db_q("""INSERT INTO orders(tg_id,total,status,delivery,name,phone,address)
                  VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id;""",
               (tg_id,total,status,delivery,prof["name"],prof["phone"],prof["address"]))
    oid = int(row[0]["id"])
    for i in items:
        db_exec("""INSERT INTO order_items(order_id,product_id,name,price,qty)
                   VALUES(%s,%s,%s,%s,%s);""",(oid,i["id"],i["name"],i["price"],i["qty"]))
    db_exec("DELETE FROM cart WHERE tg_id=%s;", (tg_id,))
    return oid

def invoice_pdf(order_id:int)->bytes:
    o = db_q("SELECT * FROM orders WHERE id=%s;", (order_id,))[0]
    items = db_q("""SELECT name,price,qty FROM order_items WHERE order_id=%s;""",(order_id,))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h-25*mm
    c.setFont("Helvetica-Bold", 16); c.drawString(20*mm, y, f"Bio Crepe Bar - Invoice #{order_id}"); y-=10*mm
    c.setFont("Helvetica", 11)
    c.drawString(20*mm,y, f"Name: {o['name']}"); y-=6*mm
    c.drawString(20*mm,y, f"Phone: {o['phone']}"); y-=6*mm
    c.drawString(20*mm,y, f"Address: {o['address']}"); y-=10*mm
    c.drawString(20*mm,y, "Items:"); y-=7*mm
    c.setFont("Helvetica",10)
    for it in items:
        c.drawString(22*mm, y, f"- {it['name']}  x{it['qty']}")
        c.drawRightString(180*mm, y, f"{it['price']*it['qty']:,}"); y-=6*mm
        if y<30*mm: c.showPage(); y = h-20*mm; c.setFont("Helvetica",10)
    y-=4*mm
    c.setFont("Helvetica-Bold",12)
    c.drawRightString(180*mm, y, f"Total: {o['total']:,} Toman"); y-=10*mm
    c.setFont("Helvetica",9); c.drawString(20*mm, 20*mm, "Thank you!")
    c.showPage(); c.save()
    buf.seek(0)
    return buf.read()

# ====== CALLBACKS ======
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = update.effective_user; data = q.data

    if data == "home":
        await q.edit_message_text("خانه:", reply_markup=home_kb(is_admin(u))); return
    if data == "menu":
        await show_menu(update, context, edit=True); return

    # Menu item
    if data.startswith("menu:item:"):
        pid = int(data.split(":")[-1])
        r = db_q("SELECT id,name,price,photo_file_id FROM products WHERE id=%s;",(pid,))
        if not r: await q.edit_message_text("پیدا نشد."); return
        r = r[0]; txt = f"«{r['name']}» — {fmt_price(r['price'])}"
        if r["photo_file_id"]:
            try:
                await q.edit_message_media(InputMediaPhoto(r["photo_file_id"], caption=txt))
                await q.edit_message_caption(caption=txt, reply_markup=menu_item_kb(pid))
            except Exception:
                await q.edit_message_text(txt, reply_markup=menu_item_kb(pid))
        else:
            await q.edit_message_text(txt, reply_markup=menu_item_kb(pid))
        return

    # Cart
    if data == "cart":
        items = db_q("""SELECT c.product_id p, p.name, p.price, c.qty
                        FROM cart c JOIN products p ON p.id=c.product_id
                        WHERE c.tg_id=%s ORDER BY p.id;""",(u.id,))
        if not items:
            await q.edit_message_text("سبد شما خالیه.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منو", callback_data="menu")],
                [InlineKeyboardButton("خانه", callback_data="home")]
            ])); return
        total = sum(i["price"]*i["qty"] for i in items)
        lines = [f"{i['name']} × {i['qty']} — {fmt_price(i['price']*i['qty'])}" for i in items]
        kb=[]
        for i in items:
            kb.append([InlineKeyboardButton(f"➖ {i['name']}",callback_data=f"cart:dec:{i['p']}"),
                       InlineKeyboardButton("➕",callback_data=f"cart:inc:{i['p']}"),
                       InlineKeyboardButton("🗑",callback_data=f"cart:del:{i['p']}")])
        kb += [[InlineKeyboardButton("ادامه خرید", callback_data="menu")],
               [InlineKeyboardButton("تسویه و ثبت سفارش", callback_data="checkout")],
               [InlineKeyboardButton("خانه", callback_data="home")]]
        await q.edit_message_text("سبد خرید:\n"+"\n".join(lines)+f"\n— جمع: {fmt_price(total)}",
                                  reply_markup=InlineKeyboardMarkup(kb)); return

    if data.startswith("cart:add:"):
        pid=int(data.split(":")[-1])
        db_exec("""INSERT INTO cart(tg_id,product_id,qty) VALUES(%s,%s,1)
                   ON CONFLICT (tg_id,product_id) DO UPDATE SET qty=cart.qty+1;""",(u.id,pid))
        await q.edit_message_text("به سبد اضافه شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧺 سبد خرید", callback_data="cart")],
            [InlineKeyboardButton("منو", callback_data="menu")]
        ])); return
    if data.startswith("cart:inc:"):
        pid=int(data.split(":")[-1]); db_exec("UPDATE cart SET qty=qty+1 WHERE tg_id=%s AND product_id=%s;",(u.id,pid))
        await cb(update, context); return
    if data.startswith("cart:dec:"):
        pid=int(data.split(":")[-1]); db_exec("UPDATE cart SET qty=GREATEST(qty-1,1) WHERE tg_id=%s AND product_id=%s;",(u.id,pid))
        await cb(update, context); return
    if data.startswith("cart:del:"):
        pid=int(data.split(":")[-1]); db_exec("DELETE FROM cart WHERE tg_id=%s AND product_id=%s;",(u.id,pid))
        await cb(update, context); return

    # Checkout
    if data == "checkout":
        items = db_q("""SELECT p.id,p.name,p.price,c.qty FROM cart c JOIN products p ON p.id=c.product_id
                        WHERE c.tg_id=%s;""",(u.id,))
        if not items:
            await q.edit_message_text("سبد خالیه.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منو", callback_data="menu")],
                [InlineKeyboardButton("خانه", callback_data="home")]
            ])); return
        total = sum(i["price"]*i["qty"] for i in items)
        prof = db_q("SELECT name,phone,address FROM users WHERE tg_id=%s;",(u.id,))[0]
        if not prof["name"] or not prof["phone"] or not prof["address"]:
            context.user_data["profile_step"]="name"
            await q.edit_message_text("نام و نام‌خانوادگی را ارسال کن:"); return
        context.user_data["pending_total"]=total
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 ارسال با پیک", callback_data="dlv:courier")],
            [InlineKeyboardButton("🤝 تحویل حضوری", callback_data="dlv:pickup")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])
        await q.edit_message_text(f"جمع سبد: {fmt_price(total)}\nروش تحویل:", reply_markup=kb); return

    if data.startswith("dlv:"):
        method = "courier" if data.endswith("courier") else "pickup"
        context.user_data["delivery_method"]=method
        total = int(context.user_data.get("pending_total",0))
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("پرداخت از کیف پول", callback_data="pay:wallet")],
            [InlineKeyboardButton("کارت به کارت", callback_data="pay:bank")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])
        await q.edit_message_text(f"مبلغ قابل پرداخت: {fmt_price(total)}", reply_markup=kb); return

    if data == "pay:wallet":
        total = int(context.user_data.get("pending_total",0))
        bal = wallet(u.id)
        if bal < total:
            await q.edit_message_text(f"موجودی کافی نیست. کمبود: {fmt_price(total-bal)}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("کیف پول",callback_data="wallet")],
                                                                         [InlineKeyboardButton("کارت به کارت",callback_data="pay:bank")],
                                                                         [InlineKeyboardButton("خانه",callback_data="home")]])); return
        oid = create_order_from_cart(u.id, context.user_data.get("delivery_method","courier"), as_awaiting=False)
        set_wallet(u.id, bal-total)
        await q.edit_message_text(f"سفارش #{oid} پرداخت و ثبت شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("دانلود فاکتور PDF", callback_data=f"inv:{oid}")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])); return

    if data == "pay:bank":
        oid = create_order_from_cart(u.id, context.user_data.get("delivery_method","courier"), as_awaiting=True)
        context.user_data["await_bank_proof"]=oid
        await q.edit_message_text(
            f"سفارش #{oid} ثبت شد (در انتظار پرداخت).\n"
            "مبلغ را کارت‌به‌کارت کن و «رسید یا ۴ رقم آخر کارت» را ارسال کن.\n"
            "💳 6037-xxxx-xxxx-xxxx بنام Bio Crepe Bar"
        ); return

    # Wallet
    if data == "wallet":
        bal = wallet(u.id)
        await q.edit_message_text(f"موجودی: {fmt_price(bal)}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ شارژ کارت‌به‌کارت", callback_data="wallet:topup")],
            [InlineKeyboardButton("خانه", callback_data="home")]
        ])); return
    if data == "wallet:topup":
        context.user_data["await_topup_amount"]=True
        await q.edit_message_text("مبلغ شارژ (عدد به تومان) را بفرست:"); return

    # Music
    if data == "music":
        rows = db_q("SELECT id,title FROM music ORDER BY id DESC LIMIT 20;")
        if not rows:
            await q.edit_message_text("فعلاً موزیکی نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("خانه",callback_data="home")]])); return
        kb = [[InlineKeyboardButton(f"▶️ {r['title']}", callback_data=f"music:play:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("خانه", callback_data="home")])
        await q.edit_message_text("🎵 موزیک‌ها:", reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("music:play:"):
        mid = int(data.split(":")[-1])
        r = db_q("SELECT title,file_id FROM music WHERE id=%s;", (mid,))
        if not r: await q.edit_message_text("یافت نشد."); return
        await q.edit_message_text(f"🎵 {r[0]['title']}"); await q.message.chat.send_audio(audio=r[0]["file_id"]); return

    # Invoice
    if data.startswith("inv:"):
        oid = int(data.split(":")[-1])
        pdf_bytes = invoice_pdf(oid)
        await q.message.chat.send_document(document=pdf_bytes, filename=f"invoice_{oid}.pdf", caption=f"فاکتور سفارش #{oid}")
        await q.answer("ارسال شد"); return

    # Admin panels
    if data == "admin:add":
        if not is_admin(u): return
        context.user_data["add_step"]="name"
        await q.edit_message_text("نام محصول را بفرست:"); return
    if data == "admin:manage":
        if not is_admin(u): return
        rows = db_q("SELECT id,name,price FROM products ORDER BY id;")
        if not rows: await q.edit_message_text("محصولی نیست."); return
        kb = [[InlineKeyboardButton(f"{r['id']}. {r['name']} ({fmt_price(r['price'])})", callback_data=f"admin:edit:{r['id']}")] for r in rows]
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
        pid=int(data.split(":")[-1]); db_exec("DELETE FROM products WHERE id=%s;",(pid,))
        await q.edit_message_text("حذف شد ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("مدیریت",callback_data="admin:manage")]])); return
    if data.startswith("admin:ename:"):
        if not is_admin(u): return
        context.user_data["edit_step"]=("name", int(data.split(":")[-1])); await q.edit_message_text("نام جدید:"); return
    if data.startswith("admin:eprice:"):
        if not is_admin(u): return
        context.user_data["edit_step"]=("price", int(data.split(":")[-1])); await q.edit_message_text("قیمت جدید (عدد):"); return
    if data.startswith("admin:ephoto:"):
        if not is_admin(u): return
        context.user_data["edit_step"]=("photo", int(data.split(":")[-1])); await q.edit_message_text("عکس جدید را بفرست:"); return

    # Admin orders
    if data == "admin:orders":
        if not is_admin(u): return
        rows = db_q("SELECT id,tg_id,total,status FROM orders ORDER BY id DESC LIMIT 20;")
        if not rows: await q.edit_message_text("سفارشی نیست."); return
        kb = [[InlineKeyboardButton(f"#{r['id']} — {r['status']} — {fmt_price(r['total'])}", callback_data=f"admin:order:{r['id']}")] for r in rows]
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
            [InlineKeyboardButton("📄 فاکتور", callback_data=f"inv:{oid}")],
            [InlineKeyboardButton("⬅️ لیست", callback_data="admin:orders")]
        ])
        await q.edit_message_text(txt, reply_markup=kb); return
    if data.startswith("admin:ost:"):
        if not is_admin(u): return
        _,_,oid,st = data.split(":")
        db_exec("UPDATE orders SET status=%s WHERE id=%s;", (st,int(oid)))
        await q.edit_message_text("به‌روزرسانی شد ✅", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ لیست سفارش‌ها", callback_data="admin:orders")]
        ])); return

    if data == "admin:addmusic":
        if not is_admin(u): return
        context.user_data["music_step"]="title"
        await q.edit_message_text("عنوان موزیک را بفرست:"); return

    if data == "game":
        await q.edit_message_text("🎮 به‌زودی!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("خانه",callback_data="home")]])); return

# ====== TEXT & MEDIA ======
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; ensure_user(u)
    t = (update.message.text or "").strip()

    # Profile for checkout
    p = context.user_data.get("profile_step")
    if p == "name":
        db_exec("UPDATE users SET name=%s WHERE tg_id=%s;", (t,u.id))
        context.user_data["profile_step"]="phone"; await update.message.reply_text("شماره موبایل:"); return
    if p == "phone":
        db_exec("UPDATE users SET phone=%s WHERE tg_id=%s;", (t,u.id))
        context.user_data["profile_step"]="address"; await update.message.reply_text("آدرس کامل:"); return
    if p == "address":
        db_exec("UPDATE users SET address=%s WHERE tg_id=%s;", (t,u.id))
        context.user_data.pop("profile_step",None)
        await update.message.reply_text("ذخیره شد ✅ دوباره «ثبت سفارش» را بزن."); return

    # Wallet topup
    if context.user_data.pop("await_topup_amount", False):
        if not t.isdigit(): await update.message.reply_text("عدد نامعتبر."); return
        amt=int(t); context.user_data["await_topup_ref"]=amt
        await update.message.reply_text(f"{fmt_price(amt)} را کارت‌به‌کارت کن و «رسید/۴ رقم آخر کارت» را بفرست:"); return
    if "await_topup_ref" in context.user_data:
        amt=int(context.user_data.pop("await_topup_ref"))
        db_exec("INSERT INTO topups(tg_id,amount,ref) VALUES(%s,%s,%s);",(u.id,amt,t))
        await update.message.reply_text("درخواست شارژ ثبت شد ✅ پس از تایید ادمین اعمال می‌شود.")
        if ADMIN_ID:
            try: await context.bot.send_message(ADMIN_ID, f"Topup: user {u.id} - {fmt_price(amt)} - ref:{t}")
            except: pass
        return

    # Bank proof for order
    if "await_bank_proof" in context.user_data:
        oid = int(context.user_data.pop("await_bank_proof"))
        db_exec("UPDATE orders SET proof=%s WHERE id=%s;", (t,oid))
        await update.message.reply_text(f"رسید دریافت شد ✅ سفارش #{oid} در انتظار تایید ادمین است.")
        if ADMIN_ID:
            try: await context.bot.send_message(ADMIN_ID, f"Order #{oid} proof by {u.id}: {t}")
            except: pass
        return

    # Admin add product (name/price)
    if is_admin(u) and context.user_data.get("add_step") == "name":
        context.user_data["new_name"]=t; context.user_data["add_step"]="price"
        await update.message.reply_text("قیمت (عدد):"); return
    if is_admin(u) and context.user_data.get("add_step") == "price":
        if not t.replace(",","").isdigit(): await update.message.reply_text("قیمت نامعتبر."); return
        context.user_data["new_price"]=int(t.replace(",","")); context.user_data["add_step"]="photo_or_done"
        await update.message.reply_text("اگر عکس داری الان بفرست؛ وگرنه /done"); return

    # Edit product (name/price)
    if is_admin(u) and context.user_data.get("edit_step"):
        kind,pid = context.user_data["edit_step"]
        if kind=="name":
            db_exec("UPDATE products SET name=%s WHERE id=%s;", (t,pid))
            context.user_data.pop("edit_step",None); await update.message.reply_text("نام به‌روزرسانی شد ✅"); return
        if kind=="price":
            if not t.replace(",","").isdigit(): await update.message.reply_text("قیمت نامعتبر."); return
            db_exec("UPDATE products SET price=%s WHERE id=%s;", (int(t.replace(",","")),pid))
            context.user_data.pop("edit_step",None); await update.message.reply_text("قیمت به‌روزرسانی شد ✅"); return

    # Add music title
    if is_admin(u) and context.user_data.get("music_step")=="title":
        context.user_data["music_title"]=t; context.user_data["music_step"]="file"
        await update.message.reply_text("فایل موزیک را به‌صورت Audio بفرست."); return

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if is_admin(u) and context.user_data.get("add_step")=="photo_or_done":
        context.user_data["new_photo"]=update.message.photo[-1].file_id
        await update.message.reply_text("عکس ذخیره شد. /done را بزن.")
    if is_admin(u) and context.user_data.get("edit_step"):
        kind,pid=context.user_data["edit_step"]
        if kind=="photo":
            fid=update.message.photo[-1].file_id
            db_exec("UPDATE products SET photo_file_id=%s WHERE id=%s;",(fid,pid))
            context.user_data.pop("edit_step",None); await update.message.reply_text("عکس به‌روزرسانی شد ✅")

async def audio_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if is_admin(u) and context.user_data.get("music_step")=="file":
        fid = update.message.audio.file_id
        title = context.user_data.pop("music_title","Untitled")
        context.user_data.pop("music_step",None)
        db_exec("INSERT INTO music(title,file_id) VALUES(%s,%s);",(title,fid))
        await update.message.reply_text("موزیک ذخیره شد ✅")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_admin(u): return
    if context.user_data.get("add_step")!="photo_or_done":
        await update.message.reply_text("جریان افزودن فعال نیست."); return
    name=context.user_data.pop("new_name",None)
    price=context.user_data.pop("new_price",None)
    photo=context.user_data.pop("new_photo",None)
    context.user_data.pop("add_step",None)
    if not name or price is None:
        await update.message.reply_text("نام/قیمت ناقص است."); return
    db_exec("INSERT INTO products(name,price,photo_file_id) VALUES(%s,%s,%s);",(name,price,photo))
    await update.message.reply_text("محصول ثبت شد ✅")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# ====== BUILD ======
def build_app()->Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.AUDIO, audio_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    return app

if __name__ == "__main__":
    migrate()
    application = build_app()
    webhook_url = WEBHOOK_URL.rstrip("/") + f"/{BOT_TOKEN}"
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        stop_signals=None
    )
