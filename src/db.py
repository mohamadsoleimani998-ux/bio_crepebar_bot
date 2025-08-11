# db.py
# دیتابیس ساده با دیکشنری (حافظه موقت)

users_wallet = {}
products_list = [
    "قهوه اسپرسو - ۵۰,۰۰۰ تومان",
    "لاته - ۶۰,۰۰۰ تومان",
    "کاپوچینو - ۵۵,۰۰۰ تومان"
]

def get_wallet(user_id):
    return users_wallet.get(user_id, 0)

def update_wallet(user_id, amount):
    users_wallet[user_id] = get_wallet(user_id) + amount

def get_products():
    return products_list
