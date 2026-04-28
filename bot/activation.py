
import json
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))  # your Telegram numeric user ID
DATA_FILE = "/data/activated_chats.json"

def load_activated_chats() -> set[int]:
    if not os.path.exists(DATA_FILE):
        return set()
    with open(DATA_FILE, "r") as f:
        return set(json.load(f))

def save_activated_chats(chats: set[int]) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(list(chats), f)

ACTIVATED_CHATS: set[int] = load_activated_chats()

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_USER_ID

def is_activated(chat_id: int) -> bool:
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
