# src/base.py
# -*- coding: utf-8 -*-
"""
تنظیمات پایه، لاگینگ و خواندن متغیرهای محیطی پروژه بات فروشگاهی.
با Render/Neon هماهنگ است.
"""

from __future__ import annotations

import os
import logging
from decimal import Decimal
from typing import Iterable, Set

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")


# ---------------------------
# Helpers
# ---------------------------
def _env(name: str, default=None, required: bool = False):
    """خواندن متغیر محیطی با هندل‌کردن مقدار پیش‌فرض/اجباری بودن."""
    val = os.environ.get(name, default)
    if required and (val is None or str(val).strip() == ""):
        raise RuntimeError(f"{name} is not set in environment variables")
    return val


def _parse_admin_ids(val: str | None) -> Set[int]:
    """
    ورودی مثل '123,456  789' → {123, 456, 789}
    """
    if not val:
        return set()
    parts: Iterable[str] = [p.strip() for p in val.replace("؛", ",").replace(" ", ",").split(",")]
    out: Set[int] = set()
    for p in parts:
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            log.warning("ADMIN_IDS contains a non-numeric value: %r", p)
    return out


def toman(n: Decimal | int | float) -> str:
    """
    قالب‌بندی عدد به تومان با جداکننده هزارگان.
    مثال: 125000 → '125,000 تومان'
    """
    try:
        num = Decimal(n)
    except Exception:
        return f"{n} تومان"
    q = f"{int(num):,}"
    return f"{q} تومان"


# ---------------------------
# Environment & constants
# ---------------------------

# دیتابیس (برای db.py لازم است)
DATABASE_URL: str = _env("DATABASE_URL", required=True)

# توکن بات
# امکان سازگاری با هر دو نام رایج:
BOT_TOKEN: str = _env("BOT_TOKEN", default=_env("TELEGRAM_TOKEN"), required=True)

# آدرس عمومی سرویس (برای وبهوک)
PUBLIC_URL: str = _env("PUBLIC_URL", default=_env("WEBHOOK_BASE"))
if PUBLIC_URL:
    PUBLIC_URL = PUBLIC_URL.rstrip("/")

# وبهوک (اختیاری؛ اگر خالی باشد، از Polling استفاده می‌شود)
WEBHOOK_SECRET: str = _env("WEBHOOK_SECRET", default="T3legramWebhookSecret_2025")
WEBHOOK_PATH: str = _env("WEBHOOK_PATH", default="/telegram-webhook")
WEBHOOK_URL: str | None = _env("WEBHOOK_URL", default=None)
# اگر WEBHOOK_URL مشخص نشده ولی PUBLIC_URL هست، خودمان می‌سازیم:
if not WEBHOOK_URL and PUBLIC_URL:
    WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"

# ادمین‌ها
ADMIN_IDS = _parse_admin_ids(_env("ADMIN_IDS", default=""))

# درصد کش‌بک
try:
    CASHBACK_PERCENT: int = int(str(_env("CASHBACK_PERCENT", default="3")).strip())
except Exception:
    CASHBACK_PERCENT = 3

# واحد پول
CURRENCY = "تومان"

# سایر تنظیمات عمومی ربات
PAGE_SIZE = 6  # تعداد آیتم منو در هر صفحه
BRAND_NAME = _env("BRAND_NAME", default="کافه")
