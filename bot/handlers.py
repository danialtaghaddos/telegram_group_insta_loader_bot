# bot/handlers.py
from typing import Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger


def is_youtube_url(url: str) -> bool:
    """Check if the URL is a YouTube URL"""
    return "youtube.com" in url or "youtu.be" in url


async def handle_message(urls: list[Any], update: Update, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None):
    for i, url in enumerate(urls, 1):
        reply_id = reply_to_message_id or update.message.message_id

        # Check if this is a YouTube URL - ask for confirmation
        if is_youtube_url(url):
            keyboard = [
                [
                    InlineKeyboardButton("🎵 Download Audio", callback_data=f"yt_audio_{i}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"yt_cancel_{i}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            status_msg = await update.message.reply_text(
                f"Do you want to download this as audio?",
                reply_to_message_id=reply_id,
                reply_markup=reply_markup
            )
            
            # Store the URL and status message for callback handling
            context.chat_data.setdefault("yt_urls", {})[str(i)] = {
                "url": url,
                "status_msg_id": status_msg.message_id,
                "reply_to_message_id": reply_id
            }
        else:
            # Non-YouTube URLs proceed directly
            status_text = f"🤖 I'm on it boss..." if len(urls) == 1 else f"🔜 Items ahead:{len(urls)} — Will get to work soon..."
            
            status_msg = await update.message.reply_text(
                status_text,
                reply_to_message_id=reply_id
            )
            
            # Store the original reply_to_message_id to be used later
            await queue.put((update, context, url, status_msg, reply_to_message_id, update.message))


async def handle_youtube_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for YouTube download confirmation"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    
    # Get the stored URLs for this chat
    yt_urls = context.chat_data.get("yt_urls", {})
    
    # Parse the callback data
    parts = data.split("_")
    if len(parts) < 3:
        return
    
    action = parts[1]  # "audio" or "cancel"
    url_index = parts[2]  # The index of the URL
    
    # Find the URL info
    url_info = None
    for key, value in yt_urls.items():
        if key == url_index:
            url_info = value
            break
    
    if not url_info:
        try:
            await query.message.delete()
        except:
            pass
        return
    
    url = url_info["url"]
    original_reply_to_message_id = url_info.get("reply_to_message_id")
    
    if action == "cancel":
        # User cancelled - delete the question message
        try:
            await query.message.delete()
        except:
            try:
                await query.message.edit_text("❌ Cancelled.")
            except:
                pass
        return
    
    if action == "audio":
        # User wants audio - delete the question and show processing message
        try:
            await query.message.delete()
        except:
            pass
        
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🎵 Downloading audio...",
            reply_to_message_id=original_reply_to_message_id
        )
        
        # Get the original message that triggered this (the one with the YouTube link)
        try:
            original_message = await context.bot.get_message(
                chat_id=chat_id,
                message_id=original_reply_to_message_id
            )
        except:
            original_message = None
        
        # Add to queue for processing - pass original_message as the message to reply with
        await queue.put((update, context, url, status_msg, original_reply_to_message_id, original_message))
        
        # Clean up the stored URL info
        if url_index in yt_urls:
            del yt_urls[url_index]