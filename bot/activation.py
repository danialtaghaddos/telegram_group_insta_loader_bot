
import json
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes
from .config import logger

DEBUG = bool(os.getenv("DEBUG_BOT"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))  # your Telegram numeric user ID
DATA_FILE = "/data/activated_chats.json"
DOORMAN_FILE = "/data/doorman_chats.json"

def load_activated_chats() -> set[int]:
    if not os.path.exists(DATA_FILE):
        return set()
    with open(DATA_FILE, "r") as f:
        return set(json.load(f))

def save_activated_chats(chats: set[int]) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(list(chats), f)

def load_doorman_chats() -> set[int]:
    if not os.path.exists(DOORMAN_FILE):
        return set()
    with open(DOORMAN_FILE, "r") as f:
        return set(json.load(f))

def save_doorman_chats(chats: set[int]) -> None:
    with open(DOORMAN_FILE, "w") as f:
        json.dump(list(chats), f)

ACTIVATED_CHATS: set[int] = load_activated_chats()
DOORMAN_CHATS: set[int] = load_doorman_chats()

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_USER_ID

def is_activated(chat_id: int) -> bool:
    if DEBUG:
        return True
    return chat_id in ACTIVATED_CHATS

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    chat_id = update.effective_chat.id
    ACTIVATED_CHATS.add(chat_id)
    save_activated_chats(ACTIVATED_CHATS)

    await update.message.reply_text("✅ Bot activated for this chat.")

async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    chat_id = update.effective_chat.id
    ACTIVATED_CHATS.discard(chat_id)
    save_activated_chats(ACTIVATED_CHATS)

    await update.message.reply_text("⛔ Bot deactivated for this chat.")


async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    if not ACTIVATED_CHATS:
        await update.message.reply_text("No chats activated.")
        return

    urls = []
    for chat_id in sorted(ACTIVATED_CHATS):
        # Convert private chat IDs (e.g., -100123456789) to t.me URLs
        chat_id_str = str(chat_id)
        if chat_id_str.startswith("-100"):
            # Private supergroup/channel
            url = f"https://t.me/c/{chat_id_str[4:]}"
        elif chat_id < 0:
            # Regular group (negative ID without -100 prefix)
            url = f"https://t.me/c/{chat_id_str[1:]}"
        else:
            # Private user chat
            url = f"https://t.me/{chat_id_str}"
        urls.append(f"{url} (ID: {chat_id})")

    await update.message.reply_text("Activated chats:\n" + "\n".join(urls))


async def doorman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle doorman mode for the current chat - auto-deletes join/leave system messages."""
    if not is_admin(update):
        return

    chat_id = update.effective_chat.id
    
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
