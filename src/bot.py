import os
import json
from fastapi import FastAPI, Request

from handlers import handle_update
from db import init_db  # فقط برای ساخت جداول/ستون‌ها

app = FastAPI()

# بدون تغییر مسیر وبهوک
@app.on_event("startup")
def _startup():
    # ساخت امن جداول/ستون‌ها (اگر موجود باشند کاری نمی‌کند)
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        # اگر هم خطایی بود سرویس لایو می‌ماند و در لاگ می‌بینیم
        print("init_db error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
