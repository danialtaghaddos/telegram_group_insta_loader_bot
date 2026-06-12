# bot/handlers.py
from typing import Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger, active_tasks, get_next_task_id


async def handle_message(urls: list[Any], update: Update, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None):
    """Handle incoming messages with social media URLs."""
    for i, url in enumerate(urls, 1):
        reply_id = reply_to_message_id or update.message.message_id
        
        # All URLs proceed directly to download (no YouTube choice)
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
        await queue.put((update, context, url, status_msg, reply_id, update.message, task_id))


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


