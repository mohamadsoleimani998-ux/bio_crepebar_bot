import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests

from .db import ensure_schema, get_or_create_user, get_products

# --- هنگام استارت، اسکیمای دیتابیس تضمین می‌شود
ensure_schema()

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

app = FastAPI()

# ------------------ متد ارسال پیام ------------------
def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

# ------------------ وبهوک ------------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    message = data.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")

    if not chat_id or not text:
        return JSONResponse({"ok": True})

    # ثبت یا گرفتن کاربر
    get_or_create_user(chat_id)

    # دستورات
    if text.startswith("/start"):
        send_message(chat_id, "سلام! به ربات خوش آمدید.\nدستورات: /wallet , /products")
    elif text.startswith("/wallet"):
        user = get_or_create_user(chat_id)
        send_message(chat_id, f"موجودی کیف پول: {user['wallet_cents']} تومان")
    elif text.startswith("/products"):
        products = get_products()
        if not products:
            send_message(chat_id, "محصولی موجود نیست.")
        else:
            for p in products:
                send_message(chat_id, f"{p['title']} - قیمت: {p['price_cents']} تومان")
    else:
        send_message(chat_id, "دستور ناشناخته.")

    return JSONResponse({"ok": True})
