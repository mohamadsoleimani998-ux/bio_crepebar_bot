import os
import json
from fastapi import FastAPI, Request
from handlers import handle_update

app = FastAPI()

@app.post(f"/{os.getenv('BOT_TOKEN')}")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
