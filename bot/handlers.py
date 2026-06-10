# bot/handlers.py
from typing import Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger, active_tasks, get_next_task_id


def is_youtube_url(url: str) -> bool:
    """Check if the URL is a YouTube URL"""
    url_lower = url.lower()
    return ("youtube.com" in url_lower or "m.youtube.com" in url_lower or "youtu.be" in url_lower)


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
            
            # Create cancel button keyboard
            task_id = get_next_task_id()
            cancel_keyboard = [
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]
            ]
            cancel_markup = InlineKeyboardMarkup(cancel_keyboard)
            
            status_msg = await update.message.reply_text(
                status_text,
                reply_to_message_id=reply_id,
                reply_markup=cancel_markup
            )
            
            # Track this active task for cancellation
            active_tasks[task_id] = {
                "cancelled": False,
                "temp_dir": None,
                "status_msg": status_msg,
                "chat_id": update.effective_chat.id if update.effective_chat else None,
                "url": url
            }
            
            # Store the original reply_to_message_id to be used later
            await queue.put((update, context, url, status_msg, reply_to_message_id, update.message, task_id))


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
        # User wants audio - delete the question and show processing message with cancel button
        try:
            await query.message.delete()
        except:
            pass
        
        # Create task ID and cancel button for the download
        task_id = get_next_task_id()
        cancel_keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]
        ]
        cancel_markup = InlineKeyboardMarkup(cancel_keyboard)
        
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🎵 Downloading audio...",
            reply_to_message_id=original_reply_to_message_id,
            reply_markup=cancel_markup
        )
        
        # Track this active task for cancellation
        active_tasks[task_id] = {
            "cancelled": False,
            "temp_dir": None,
            "status_msg": status_msg,
            "chat_id": chat_id,
            "url": url
        }
        
        # Get the original message that triggered this (the one with the YouTube link)
        try:
            original_message = await context.bot.get_message(
                chat_id=chat_id,
                message_id=original_reply_to_message_id
            )
        except:
            original_message = None
        
        # Add to queue for processing - pass original_message as the message to reply with
        await queue.put((update, context, url, status_msg, original_reply_to_message_id, original_message, task_id))
        
        # Clean up the stored URL info
        if url_index in yt_urls:
            del yt_urls[url_index]


async def handle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel button callback for active downloads"""
    query = update.callback_query
    await query.answer("Cancelling...")
    
    data = query.data
    # Parse task_id from callback data "cancel_{task_id}"
    parts = data.split("_", 1)
    if len(parts) < 2:
        return
    
    try:
        task_id = int(parts[1])
    except ValueError:
        return
    
    # Check if task exists
    if task_id not in active_tasks:
        try:
            await query.message.delete()
        except:
            pass
        return
    
    task_info = active_tasks[task_id]
    
    # Mark as cancelled
    task_info["cancelled"] = True
    
    # Clean up temp directory if it exists
    if task_info.get("temp_dir"):
        try:
            import shutil
            shutil.rmtree(task_info["temp_dir"], ignore_errors=True)
            logger.info(f"Cleaned up temp directory {task_info['temp_dir']} for cancelled task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to clean up temp directory for task {task_id}: {e}")
    
    # Update status message
    try:
        await query.message.edit_text("❌ Download cancelled.")
    except Exception as e:
        logger.warning(f"Failed to edit status message for cancellation: {e}")
        try:
            await query.message.delete()
        except:
            pass
    
    # Remove from active_tasks after a short delay to allow the worker to see the cancellation
    # The worker will remove it from active_tasks when it processes the cancellation
    logger.info(f"Task {task_id} marked as cancelled")


async def handle_large_file_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback for large file handling choice (compress or Google Drive)"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    # Parse callback data: "compress_{task_id}" or "drive_{task_id}"
    parts = data.split("_", 1)
    if len(parts) < 2:
        return
    
    action = parts[0]  # "compress" or "drive"
    
    try:
        task_id = int(parts[1])
    except ValueError:
        return
    
    # Check if task exists
    if task_id not in active_tasks:
        try:
            await query.message.delete()
        except:
            pass
        return
    
    task_info = active_tasks[task_id]
    
    # Store the user's choice in the task info
    task_info["large_file_action"] = action
    
    # Update status message
    if action == "compress":
        try:
            await query.message.edit_text("🗜️ Compressing audio...")
        except:
            pass
    elif action == "drive":
        try:
            await query.message.edit_text("📁 Uploading to Google Drive...")
        except:
            pass
    
    logger.info(f"Task {task_id}: User chose to {action} large audio file")
