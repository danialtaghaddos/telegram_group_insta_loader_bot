# bot/main.py
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .utils import extract_social_urls
from .activation import (
    ACTIVATED_CHATS,
    activate,
    deactivate,
    list_chats,
    doorman,
    doorman_message_handler,
    is_activated,
    load_activation_state,
)
from .moderators import (
    access_command,
    approve_command,
    deny_command,
    add_moderator_command,
    remove_moderator_command,
    list_requests_command,
    list_moderators_command,
    my_chats_command,
    help_command,
    load_command,
    is_moderator,
)
from .config import BOT_TOKEN, logger, ADMIN_USER_ID
from .handlers import handle_message, handle_cancel_callback
from .worker import worker
import re

async def on_startup(app):
    from .storage import initialize_from_telegram
    from .moderators import reload_from_storage
    await initialize_from_telegram()
    load_activation_state()
    reload_from_storage()
    for _ in range(1):
        asyncio.create_task(worker())


async def handle_admin_forwarded_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle files forwarded by admin with caption format: chat_id-status_msg_id-file_name
    
    Flow:
    1. Check if message is from admin
    2. Parse caption to get target chat_id and status_msg_id
    3. Forward the message to target chat (avoids re-downloading large file)
    4. Clean up status message and received message
    """
    # Only process messages from the admin
    if not update.message or not update.effective_user:
        return
    
    if update.effective_user.id != ADMIN_USER_ID:
        return
    
    # Check for caption (required for our format)
    message = update.message
    caption = message.caption if message.caption else ""
    
    # Parse caption format: chat_id-status_msg_id-original_reply_to_message_id-file_name
    # Example: "123456789-42-987654321-video.mp4"
    match = re.match(r'^(-?\d+)-(\d+)-(\d+)-(.+)$', caption)
    if not match:
        return  # Not our special format, ignore
    
    target_chat_id = int(match.group(1))
    status_msg_id = int(match.group(2))
    original_reply_to_message_id = int(match.group(3))
    file_name = match.group(4)
    
    logger.info(f"Received large file from admin: chat_id={target_chat_id}, status_msg_id={status_msg_id}, original_reply_to_message_id={original_reply_to_message_id}, file={file_name}")
    
    try:
        # Forward the message to target chat (avoids re-uploading the large file)
        await context.bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
            caption=''  # Optionally set caption to file name in target chat
        )
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=f"✅ Your file is ready. 👆",
            reply_to_message_id=original_reply_to_message_id
        )
        logger.info(f"✅ Forwarded large file to chat {target_chat_id}")
        
    except Exception as e:
        logger.error(f"Failed to forward message to {target_chat_id}: {e}")
    
    # Clean up: delete the received message from bot chat
    try:
        await message.delete()
        logger.info(f"Deleted received file message {message.message_id}")
    except Exception as e:
        logger.warning(f"Failed to delete received message: {e}")
    
    # Clean up: delete the status message if it still exists
    if status_msg_id:
        try:
            await context.bot.delete_message(
                chat_id=target_chat_id,
                message_id=status_msg_id
            )
            logger.info(f"Deleted status message {status_msg_id} in chat {target_chat_id}")
        except Exception as e:
            logger.debug(f"Failed to delete status message (may have been already deleted): {e}")


async def protected_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not update.message or not update.message.text:
        return
    
    urls = extract_social_urls(update.message.text)
    if not urls:
        return
    
    if not is_activated(chat_id):
        if update.effective_chat and update.effective_chat.type == "private" and update.effective_user and is_moderator(update.effective_user.id):
            pass  # Allow moderator in private chat
        else:
            return
    
    logger.info("Received message in chat %s: %s - activated: %s - effective chat: %s",
                 chat_id,
                   update.message.text,
                     is_activated(chat_id),
                       update.effective_user.id if update.effective_chat else None)
    await handle_message(urls, update, context)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    # Core bot commands
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("deactivate", deactivate))
    app.add_handler(CommandHandler("doorman", doorman))

    # Admin-only commands
    app.add_handler(CommandHandler("listChats", list_chats))

    # Moderator access request commands
    app.add_handler(CommandHandler("access", access_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("deny", deny_command))

    # Moderator management commands (admin)
    app.add_handler(CommandHandler("addMods", add_moderator_command))
    app.add_handler(CommandHandler("removemod", remove_moderator_command))
    app.add_handler(CommandHandler("requests", list_requests_command))
    app.add_handler(CommandHandler("listMods", list_moderators_command))

    # Moderator info commands
    app.add_handler(CommandHandler("myChats", my_chats_command))

    # Help command
    app.add_handler(CommandHandler("help", help_command))

    # Admin load command (reply to message with links to download)
    app.add_handler(CommandHandler("load", load_command))

    # Cancel callback handler for active downloads
    app.add_handler(CallbackQueryHandler(handle_cancel_callback, pattern=r"^cancel_\d+$"))

    # Doorman message handler - must be before other message handlers
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        doorman_message_handler
    ))

    # example protected message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, protected_handler))

    # Handler for large files forwarded by admin
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.AUDIO | filters.VIDEO | filters.PHOTO,
        handle_admin_forwarded_file
    ))

    app.run_polling()

if __name__ == "__main__":
    main()