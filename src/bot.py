import os
from fastapi import FastAPI, Request

# ایمپورت نسبی چون برنامه به صورت پکیج src اجرا می‌شود
from .handlers import handle_update

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
