import os

from telegram import Update
from telegram.ext import ContextTypes
from .config import logger
from .storage import (
    load_activated_chats,
    save_activated_chats,
    load_doorman_chats,
    save_doorman_chats,
)

DEBUG = os.getenv("DEBUG_BOT", "").lower() in ("true", "1", "yes", "t")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))  # your Telegram numeric user ID

# Import moderator functions
from .moderators import is_admin as check_is_admin, is_moderator

ACTIVATED_CHATS: set[int] = set()
DOORMAN_CHATS: set[int] = set()


def load_activation_state() -> None:
    """Load activation-related state after the application has started."""
    global ACTIVATED_CHATS, DOORMAN_CHATS

    ACTIVATED_CHATS = load_activated_chats()
    DOORMAN_CHATS = load_doorman_chats()

    logger.info(
        "Loaded activation state: %s activated chats, %s doorman chats",
        len(ACTIVATED_CHATS),
        len(DOORMAN_CHATS),
    )
    logger.debug("Activated chats: %s", ACTIVATED_CHATS)
    logger.debug("Doorman chats: %s", DOORMAN_CHATS)


def can_moderate_chat(update: Update) -> bool:
    """Check if user can moderate (admin or moderator)."""
    if update.effective_user and update.effective_user.id == ADMIN_USER_ID:
        return True
    if update.effective_user:
        # Check if user is a moderator (can moderate chat)
        from .moderators import moderators
        if update.effective_user.id in moderators:
            return True
    return False


def is_activated(chat_id: int) -> bool:
    """Check if bot is activated for a chat. In DEBUG mode, all chats are activated."""
    logger.info(f"Debug Mode env: {os.getenv('DEBUG_BOT')}")
    if DEBUG:
        logger.info(f"DEBUG mode: treating all chats as activated. Chat ID: {chat_id}")
        return True
    activated = chat_id in ACTIVATED_CHATS
    logger.info(f"Checking activation for chat {chat_id}: {activated}")
    return activated


def escape_markdown(text: str) -> str:
    """Escape special Markdown characters."""
    if not text:
        return text
    escape_chars = r'\_`['
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /activate command. Only moderators/admins can activate."""
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or f"Chat {chat_id}"

    if not update.effective_user:
        return

    # Check if user is a moderator or admin
    if not can_moderate_chat(update):
        await update.message.reply_text("❌ Not authorized. Only moderators can activate the bot.")
        return

    # Add to set (no-op if already present) and save
    ACTIVATED_CHATS.add(chat_id)
    save_activated_chats(ACTIVATED_CHATS)
    logger.info("Activated chat: %s (total: %s)", chat_id, len(ACTIVATED_CHATS))
    await update.message.reply_text("✅ Bot activated for this chat.")


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not can_moderate_chat(update):
        await update.message.reply_text("❌ Not authorized. Only moderators can deactivate the bot.")
        return

    ACTIVATED_CHATS.discard(chat_id)
    save_activated_chats(ACTIVATED_CHATS)

    await update.message.reply_text("⛔ Bot deactivated for this chat.")


async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all activated chats (admin only)."""
    if update.effective_user.id != ADMIN_USER_ID:
        return

    if not ACTIVATED_CHATS:
        await update.message.reply_text("No chats activated.")
        return

    urls = []
    for chat_id in sorted(ACTIVATED_CHATS):
        url = None

        # First try the bot API
        try:
            chat = await context.bot.get_chat(chat_id)
            if chat.username:
                url = f"https://t.me/{chat.username}"
            elif chat.type in [chat.type.PRIVATE, chat.type.SENDER]:
                url = f"tg://user?id={chat_id}"
        except Exception as e:
            logger.debug(f"Failed to get chat info via bot API for {chat_id}: {e}")

        # If bot API failed or no URL, try Telethon
        if not url:
            try:
                from .telethon_client import get_chat_info
                info = await get_chat_info(chat_id)
                if info and info.get('link'):
                    url = info['link']
                elif info and info.get('username'):
                    url = f"https://t.me/{info['username']}"
            except Exception as e:
                logger.debug(f"Failed to get chat info via Telethon for {chat_id}: {e}")

        if url:
            urls.append(f"{url} (ID: {chat_id})")
        else:
            urls.append(f"No public URL (ID: {chat_id})")

    await update.message.reply_text("Activated chats:\n" + "\n".join(urls))


async def doorman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle doorman mode for the current chat - auto-deletes join/leave system messages."""
    chat_id = update.effective_chat.id

    if not can_moderate_chat(update):
        await update.message.reply_text("❌ Not authorized. Only moderators can use doorman.")
        return

    if chat_id in DOORMAN_CHATS:
        DOORMAN_CHATS.discard(chat_id)
        save_doorman_chats(DOORMAN_CHATS)
        await update.message.reply_text("🚪 Doorman deactivated for this chat. System messages will no longer be deleted.")
    else:
        DOORMAN_CHATS.add(chat_id)
        save_doorman_chats(DOORMAN_CHATS)
        await update.message.reply_text("🚪 Doorman activated for this chat. System messages (join/leave) will be auto-deleted.")


async def doorman_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete system messages about members joining/leaving in chats with doorman enabled."""
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if chat_id not in DOORMAN_CHATS:
        return

    # Check if this is a system message about member changes
    message = update.message
    if not message:
        return

    # Types of messages to delete:
    # - new_chat_members: users joined
    # - left_chat_member: user left
    # These are indicated by the presence of these fields
    should_delete = False

    if message.new_chat_members:
        should_delete = True
    elif message.left_chat_member:
        should_delete = True

    if should_delete:
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete system message: {e}")