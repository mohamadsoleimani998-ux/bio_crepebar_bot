from fastapi import FastAPI, Request
import requests
import os

# ایمپورت اصلاح‌شده
from .handlers import handle_update

app = FastAPI()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("PUBLIC_URL") + "/webhook"

@app.on_event("startup")
async def set_webhook():
    requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    handle_update(data)
    return {"ok": True}

@app.get("/")
async def home():
    return {"status": "running"}
