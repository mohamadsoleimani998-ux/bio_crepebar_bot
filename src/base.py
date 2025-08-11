import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Render هنگام اجرا خودش env رو ست می‌کند؛ برای لوکال هم از .env پشتیبانی شود
load_dotenv(override=False)

@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str
    DATABASE_URL: str
    PUBLIC_URL: str
    ADMIN_IDS: tuple[int, ...]
    CASHBACK_PERCENT: int
    PORT: int

def _parse_admins(value: str | None) -> tuple[int, ...]:
    if not value:
        return tuple()
    return tuple(int(x.strip()) for x in value.replace(',', ' ').split() if x.strip().isdigit())

def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    db_url = os.getenv("DATABASE_URL", os.getenv("DATABASE_URL".lower(), "")).strip()
    public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
    admins = _parse_admins(os.getenv("ADMIN_IDS"))
    cashback = int(os.getenv("CASHBACK_PERCENT", "3"))
    port = int(os.getenv("PORT", "10000"))
    if not token:
        raise RuntimeError("BOT_TOKEN is missing")
    if not db_url:
        raise RuntimeError("DATABASE_URL is missing")
    if not public_url:
        raise RuntimeError("PUBLIC_URL is missing")
    return Settings(
        BOT_TOKEN=token,
        DATABASE_URL=db_url,
        PUBLIC_URL=public_url,
        ADMIN_IDS=admins,
        CASHBACK_PERCENT=cashback,
        PORT=port,
    )

SETTINGS = get_settings()
