from fastapi import FastAPI, Request
from .base import ensure_env
from .handlers import handle_update, startup_warmup

app = FastAPI()

@app.on_event("startup")
def _startup():
    # چک کردن env و آماده‌سازی DB + وبهوک
    try:
        ensure_env()
        startup_warmup()
    except Exception as e:
        # حتی اگر خطا باشد، سرویس را لایو نگه می‌داریم و خطا را لاگ می‌کنیم
        print("startup error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
