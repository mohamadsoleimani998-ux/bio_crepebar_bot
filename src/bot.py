import os
from fastapi import FastAPI, Request
from .handlers import handle_update   # ایمپورت نسبی

app = FastAPI()

# همون مسیر وبهوک قبلی: /<BOT_TOKEN>
@app.post(f"/{os.getenv('BOT_TOKEN')}")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok"}
