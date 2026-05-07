# bot/main.py
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .utils import extract_social_urls
from .activation import (
    activate,
    deactivate,
    list_chats,
    doorman,
    doorman_message_handler,
    is_activated,
    approve_activation,
    deny_activation,
    list_activation_requests
)
from .moderators import (
    access_command,
    approve_command,
    deny_command,
    access_enabled_command,
    access_disabled_command,
    add_moderator_command,
    remove_moderator_command,
    list_requests_command,
    list_moderators_command,
    my_chats_command,
    help_command,
)
from .config import BOT_TOKEN
from .handlers import handle_message
from .worker import worker

async def on_startup(app):
    for _ in range(3):
        asyncio.create_task(worker())


async def protected_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not update.message or not update.message.text:
        return
    
    urls = extract_social_urls(update.message.text)
    if not urls:
        return
    
    if not is_activated(chat_id):
        return
    await handle_message(urls, update, context)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    # Core bot commands
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("deactivate", deactivate))
    app.add_handler(CommandHandler("doorman", doorman))

    # Activation request management (admin)
    app.add_handler(CommandHandler("approve_activation", approve_activation))
    app.add_handler(CommandHandler("deny_activation", deny_activation))
    app.add_handler(CommandHandler("activation_requests", list_activation_requests))

    # Admin-only commands
    app.add_handler(CommandHandler("listChats", list_chats))

    # Moderator access request commands
    app.add_handler(CommandHandler("access", access_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("deny", deny_command))
    app.add_handler(CommandHandler("access_enabled", access_enabled_command))
    app.add_handler(CommandHandler("access_disabled", access_disabled_command))

    # Moderator management commands (admin)
    app.add_handler(CommandHandler("addmod", add_moderator_command))
    app.add_handler(CommandHandler("removemod", remove_moderator_command))
    app.add_handler(CommandHandler("requests", list_requests_command))
    app.add_handler(CommandHandler("listmods", list_moderators_command))

    # Moderator info commands
    app.add_handler(CommandHandler("myChats", my_chats_command))

    # Help command
    app.add_handler(CommandHandler("help", help_command))

    # Doorman message handler - must be before other message handlers
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        doorman_message_handler
    ))

    # example protected message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, protected_handler))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()