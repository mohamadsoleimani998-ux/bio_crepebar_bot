from decimal import Decimal
from typing import Optional, Tuple
import psycopg2
from psycopg2 import extras

# ... بقیه ایمپورت‌ها و اتصال ...

def upsert_user(tg_id: int, name: Optional[str]) -> Tuple[int, Decimal]:
    """
    کاربر را با telegram_id درج می‌کند؛ اگر بود، فقط name (در صورت ارسال) را به‌روزرسانی می‌کند.
    در نهایت user_id و موجودی کیف پول (balance) را برمی‌گرداند.
    """
    sql = """
        INSERT INTO users (telegram_id, name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
            SET name = COALESCE(EXCLUDED.name, users.name)
        RETURNING user_id, COALESCE(balance, 0);
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (tg_id, name))
            row = cur.fetchone()
            # row = (user_id, balance)
            return row[0], row[1]
