import os
from telegram.ext import Application
from src.handlers import register

BOT_TOKEN = os.environ["BOT_TOKEN"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")
PORT = int(os.environ.get("PORT", "5000"))

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    register(application)

    async def _setup_webhook(app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        webhook_url = f"{PUBLIC_URL}/webhook"
        await app.bot.set_webhook(url=webhook_url, allowed_updates=["message","callback_query"])
        print(f"==> Webhook set to: {webhook_url}")

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        stop_signals=None,
        bootstrap_retries=3,
        on_startup=[_setup_webhook],
    )

if __name__ == "__main__":
    main()
