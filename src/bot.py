import json
from fastapi import FastAPI, Request

# ایمپورت نسبی تا در محیط پکیجی درست کار کند
from .handlers import handle_update, startup_warmup

app = FastAPI()


@app.on_event("startup")
def _startup():
    """
    در شروع سرویس: اسکیما را می‌سازد (اگر نبود)،
    ادمین‌ها را علامت‌گذاری می‌کند.
    """
    try:
        startup_warmup()
        print("Startup warmup OK")
    except Exception as e:
        # اگر هم خطا باشد، سرویس لایو می‌ماند و فقط لاگ می‌دهیم
        print("startup_warmup error:", e)


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
