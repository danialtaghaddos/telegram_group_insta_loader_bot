# bot/main.py
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
)
from .config import BOT_TOKEN
from .handlers import handle_message
from .worker import worker

async def on_startup(app):
    for _ in range(2):
        asyncio.create_task(worker())


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()