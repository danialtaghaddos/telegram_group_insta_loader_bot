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
from .activation import activate, deactivate, list_chats, doorman, doorman_message_handler, is_activated
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
        await update.message.reply_text("❌ Bot is not activated in this chat. ❌\nContact admin on www.mehreran.org")
        return
    await handle_message(urls, update, context)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()


    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("deactivate", deactivate))
    app.add_handler(CommandHandler("listChats", list_chats))
    app.add_handler(CommandHandler("doorman", doorman))

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