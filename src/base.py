import os

# Token و آدرس دیتابیس را از متغیرهای محیطی بگیر
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()  # شکل: postgres://...

# آدرس پابلیک سرویس روی Render (برای ست کردن وبهوک)
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()  # مثلا https://bio-crepebar-bot.onrender.com

def ensure_env():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
