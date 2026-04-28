# bot/handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    urls = extract_social_urls(update.message.text)
    if not urls:
        return

    for i, url in enumerate(urls, 1):
        status_text = f"🤖 I'm on in boss..." if len(urls) == 1 else f"🔜 Items ahead:{len(urls)} — Will get to work soon..."

        status_msg = await update.message.reply_text(
            status_text,
            reply_to_message_id=update.message.message_id
        )

        await queue.put((update, context, url, status_msg))


