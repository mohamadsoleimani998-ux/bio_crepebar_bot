# src/bot.py  (فقط نشان می‌دهم چه چیزی باید باشد)
import os
import json
from fastapi import FastAPI, Request

from handlers import handle_update, startup_warmup

app = FastAPI()

@app.on_event("startup")
def _startup():
    try:
        startup_warmup()
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await maybe_async(handle_update, update)
    return {"ok": True}

# اگر handle_update همگام است:
def maybe_async(fn, *args, **kwargs):
    res = fn(*args, **kwargs)
    return res

@app.get("/")
async def root():
    return {"status": "bot is running"}
