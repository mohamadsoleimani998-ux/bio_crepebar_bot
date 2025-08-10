from fastapi import FastAPI, Request
from src.handlers import handle_update, startup_warmup
# اگر لازم شد:
# from src.db import init_db

app = FastAPI()

@app.on_event("startup")
async def _startup():
    try:
        # init_db()
        await startup_warmup()
        print("startup OK")
    except Exception as e:
        print("startup warn:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
