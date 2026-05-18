# bot/handlers.py
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger

async def handle_message(urls: list[Any], update: Update, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None):
    for i, url in enumerate(urls, 1):
        status_text = f"🤖 I'm on it boss..." if len(urls) == 1 else f"🔜 Items ahead:{len(urls)} — Will get to work soon..."

        reply_id = reply_to_message_id or update.message.message_id

        status_msg = await update.message.reply_text(
            status_text,
            reply_to_message_id=reply_id
        )

        # Store the original reply_to_message_id to be used later
        await queue.put((update, context, url, status_msg, reply_to_message_id))
