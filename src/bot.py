import os
from fastapi import FastAPI, Request
from .handlers import handle_update

app = FastAPI()

# وبهوک روی مسیر توکن
@app.post(f"/{os.getenv('BOT_TOKEN')}")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

# هِلث‌چک
@app.get("/")
async def root():
    return {"status": "bot is running"}
