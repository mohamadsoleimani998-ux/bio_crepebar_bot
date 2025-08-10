import os
from fastapi import FastAPI, Request

# نکته مهم: ایمپورت نسبی تا دیگر خطای ModuleNotFound نگیریم
from .handlers import handle_update, startup_warmup
from .db import init_db

app = FastAPI()


@app.on_event("startup")
async def _startup():
    """اپ راه می‌افته؛ دیتابیس ایمن آماده می‌شود و وارم‌آپ سبک انجام می‌دهیم."""
    try:
        init_db()           # اگر جداول/ستون‌ها باشند، تغییری نمی‌دهد
        await startup_warmup()
        print("startup OK")
    except Exception as e:
        # ربات لایو می‌ماند، جزئیات در لاگ
        print("startup error:", e)


@app.post("/webhook")
async def webhook(request: Request):
    """ورودی وبهوک تلگرام را می‌گیرد و به هندلر می‌دهد."""
    update = await request.json()
    await handle_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
