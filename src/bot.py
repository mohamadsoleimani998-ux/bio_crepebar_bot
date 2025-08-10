from fastapi import FastAPI, Request
import os
from src.handlers import handle_update  # اصلاح ایمپورت

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    await handle_update(data)
    return {"ok": True}
