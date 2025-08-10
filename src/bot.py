import os
from fastapi import FastAPI, Request

# مهم: چون uvicorn با ماژول src اجرا می‌شود، باید از نام پکیج استفاده کنیم
from src.handlers import handle_update
from src.db import init_db  # فقط برای اطمینان از ساخت/به‌روز شدن جداول در استارت

app = FastAPI()

@app.on_event("startup")
def _startup():
    # تلاش امن برای آماده‌سازی دیتابیس (اگر چیزی نباشد، سرویس لایو می‌ماند)
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
