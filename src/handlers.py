# src/handlers.py
from typing import Dict, Any, Optional

# =========================
# ایمپورت‌های لایه Base
# =========================
# این‌ها باید وجود داشته باشند و قبلاً کار می‌کردند
from src.base import send_message, send_menu  # ← همین‌هایی که دارید

# set_my_commands ممکن است در base نباشد؛ اگر نبود، نال-اپ بگذاریم
try:
    from src.base import set_my_commands
except Exception:
    def set_my_commands(*args, **kwargs):
        # no-op
        return None


# =========================
# ایمپورت‌های دیتابیس
# =========================

# الزامـی‌ها: اگر نبودند، بگذارید خطا بده تا سریع متوجه شویم
from src.db import get_or_create_user, get_wallet, list_products  # ← همین‌هایی که قبلاً بود

# اختیاری‌ها: اگر در db.py تعریف نشده باشند، نسخه‌ی امن بگذار
try:
    from src.db import add_product
except Exception:
    def add_product(*_args, **_kwargs):
        print("WARN: add_product تعریف نشده است (db.py).")
        return None

try:
    from src.db import set_admins
except Exception:
    def set_admins(*_args, **_kwargs):
        # نال-اپ: نبودنش نباید سرویس را بخواباند
        return None

try:
    from src.db import init_db
except Exception:
    def init_db():
        # نال-اپ
        return None


# =========================
# ابزارهای کمکی داخلی
# =========================
def _get_msg(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return update.get("message") or update.get("edited_message")

def _txt(msg: Dict[str, Any]) -> str:
    return (msg.get("text") or "").strip()

def _chat_id(msg: Dict[str, Any]) -> int:
    # هم برای private و هم group درست کار می‌کند
    return msg.get("chat", {}).get("id")

def _user_fields(msg: Dict[str, Any]) -> Dict[str, Any]:
    u = msg.get("from", {}) or {}
    return {
        "tg_id": u.get("id"),
        "first_name": u.get("first_name"),
        "last_name": u.get("last_name"),
        "username": u.get("username"),
    }


# =========================
# راه‌اندازی سبک (اختیاری)
# =========================
async def startup_warmup() -> None:
    """
    صدا زده می‌شود موقع بالا آمدن سرویس.
    اگر set_my_commands داشته باشید، لیست کامندها را روی تلگرام می‌نشیند.
    نبودنش هم مشکلی ایجاد نمی‌کند.
    """
    try:
        set_my_commands([
            ("/start", "شروع"),
            ("/products", "دیدن محصولات"),
            ("/wallet", "کیف پول"),
        ])
    except Exception as e:
        print("startup_warmup warning:", e)


# =========================
# هندلر اصلی آپدیت
# =========================
async def handle_update(update: Dict[str, Any]) -> None:
    """
    فقط چیزهای لازم را انجام می‌دهد و اگر تابعی در db نبود،
    با نال-اپ‌ها سرویس را سرپا نگه می‌داریم.
    """
    try:
        msg = _get_msg(update)
        if not msg:
            return

        chat_id = _chat_id(msg)
        fields = _user_fields(msg)
        tg_id = fields["tg_id"]

        # کاربر را بساز/بگیر (الزامی است)
        try:
            get_or_create_user(
                tg_id=tg_id,
                first_name=fields["first_name"],
                last_name=fields["last_name"],
                username=fields["username"],
            )
        except Exception as e:
            # اگر این خطا بدهد بهتر است در لاگ ببینیم
            print("get_or_create_user error:", e)

        text = _txt(msg)

        # ------------------ دستورات متنی
        if text == "/start":
            hello = (
                "سلام! به ربات خوش آمدید.\n"
                "دستورات: /products , /wallet\n"
                "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم."
            )
            await send_message(chat_id, hello)
            await send_menu(chat_id)  # اگر در base پیاده‌سازی شده باشد

            return

        if text == "/products":
            try:
                items = list_products()
            except Exception as e:
                print("list_products error:", e)
                items = []

            if not items:
                await send_message(chat_id, "هنوز محصولی ثبت نشده است.")
            else:
                # نمایش بسیار ساده
                lines = []
                for it in items:
                    # تلاش برای خواندن فیلدهای متداول؛ اگر نبودند، به شکل safe چاپ می‌کنیم
                    name = getattr(it, "name", None) or it.get("name") if isinstance(it, dict) else str(it)
                    price = getattr(it, "price", None) or (it.get("price") if isinstance(it, dict) else None)
                    if price is not None:
                        lines.append(f"- {name} | {price}")
                    else:
                        lines.append(f"- {name}")
                await send_message(chat_id, "\n".join(lines) or "لیست خالی است.")
            return

        if text == "/wallet":
            try:
                cents = get_wallet(tg_id)
            except Exception as e:
                print("get_wallet error:", e)
                cents = 0
            # اگر get_wallet ریال/تومان می‌دهد، همین را چاپ می‌کنیم
            await send_message(chat_id, f"موجودی کیف پول شما: {cents} تومان")
            return

        # ------------------ افزودن محصول (نمایش نمونه‌ی ساده؛ فقط اگر add_product واقعی دارید)
        # اگر پیام عکس با کپشن بود و شما بعداً چک ادمین گذاشتید، اینجا صدا بزنید
        if "photo" in msg and msg.get("caption"):
            caption = msg["caption"].strip()
            # صرفاً نمونه: اگر کپشن با + شروع شود، تلاش برای افزودن محصول
            if caption.startswith("+"):
                try:
                    # فراخوانی امن؛ امضای واقعی add_product هرچه باشد، اینجا خطا نمی‌دهد
                    add_product(tg_id=tg_id, caption=caption, photo=msg["photo"][-1]["file_id"])
                    await send_message(chat_id, "درخواست افزوده شدن محصول ثبت شد.")
                except Exception as e:
                    print("add_product error:", e)
                    await send_message(chat_id, "ثبت محصول انجام نشد.")
            return

        # پیام‌های دیگر را فعلاً نادیده بگیر
        return

    except Exception as e:
        # هیچ‌وقت نگذارید استثناء باعث کرش پروسه شود
        print("handle_update error:", e)
        try:
            # اگر شد به کاربر هم خطا ندهیم، اما برای دیباگ مفید است
            chat_id = _chat_id(_get_msg(update) or {})
            if chat_id:
                await send_message(chat_id, "یک خطای موقتی رخ داد.")
        except Exception:
            pass
