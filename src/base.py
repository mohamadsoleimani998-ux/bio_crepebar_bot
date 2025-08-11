import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "0"))
PORT = int(os.environ.get("PORT", "8000"))  # Render می‌فرسته

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
