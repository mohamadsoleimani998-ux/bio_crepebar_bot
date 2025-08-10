# src/bot.py
from fastapi import FastAPI, Request
from threading import Thread
from handlers import handle_update   # همون ایمپورت قبلی که کار می‌کرد
from db import init_db

app = FastAPI()

@app.on_event("startup")
def _startup():
    # init_db را غیرمسدودکننده اجرا می‌کنیم تا Render سریع healthcheck بگیرد
    def _bg():
        try:
            init_db()
        except Exception as e:
            print("init_db error:", e)
    Thread(target=_bg, daemon=True).start()
    print("startup kicked")

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    # بدون وابستگی به DB پاسخ می‌دهیم
    return {"status": "bot is running"}
