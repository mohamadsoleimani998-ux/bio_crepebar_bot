import os
import json
from fastapi import FastAPI, Request

# ایمپورت‌های داخلی با پیشوند پکیج
from src.handlers import handle_update, startup_warmup
from src.db import init_db

app = FastAPI()

@app.on_event("startup")
def _startup():
    # ساخت/آپدیت امن جداول
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)

    # هر کار گرم‌کن اختیاری
    try:
        startup_warmup()
    except Exception as e:
        print("startup_warmup error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
