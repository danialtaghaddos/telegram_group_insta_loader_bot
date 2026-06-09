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
from .config import BOT_TOKEN, logger
from .handlers import handle_message, handle_youtube_callback, handle_cancel_callback
from .worker import worker

async def on_startup(app):
    load_activation_state()
    for _ in range(1):
        asyncio.create_task(worker())


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

    # YouTube callback handler (must be before message handlers to catch callbacks)
    app.add_handler(CallbackQueryHandler(handle_youtube_callback, pattern=r"^yt_(audio|cancel)_\d+$"))

    # Cancel callback handler for active downloads
    app.add_handler(CallbackQueryHandler(handle_cancel_callback, pattern=r"^cancel_\d+$"))

    # Doorman message handler - must be before other message handlers
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        doorman_message_handler
    ))

    # example protected message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, protected_handler))

    app.run_polling()

if __name__ == "__main__":
    main()