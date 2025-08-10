from fastapi import FastAPI, Request
from src.handlers import handle_update, startup_warmup
from src.db import init_db

app = FastAPI()

@app.on_event("startup")
def _startup():
    try:
        init_db()
        # تنظیم ادمین‌ها و غیره
        import anyio
        anyio.from_thread.run(startup_warmup)
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
