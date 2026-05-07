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
ACTIVATION_REQUESTS_FILE = "/data/activation_requests.json"

# Import moderator functions
from .moderators import is_admin as check_is_admin, is_moderator

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

def load_activation_requests() -> list[dict]:
    """Load pending activation requests from file."""
    if not os.path.exists(ACTIVATION_REQUESTS_FILE):
        return []
    with open(ACTIVATION_REQUESTS_FILE, "r") as f:
        return json.load(f)

def save_activation_requests(requests: list[dict]) -> None:
    """Save activation requests to file."""
    with open(ACTIVATION_REQUESTS_FILE, "w") as f:
        json.dump(requests, f)

ACTIVATED_CHATS: set[int] = load_activated_chats()
DOORMAN_CHATS: set[int] = load_doorman_chats()
ACTIVATION_REQUESTS: list[dict] = load_activation_requests()


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
    if DEBUG:
        return True
    return chat_id in ACTIVATED_CHATS


def has_pending_activation_request(chat_id: int) -> bool:
    """Check if there's a pending activation request for this chat."""
    return any(req["chat_id"] == chat_id and req["status"] == "pending" for req in ACTIVATION_REQUESTS)


async def notify_admin_of_activation_request(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                              chat_id: int, chat_title: str, 
                                              user_id: int, username: str, 
                                              first_name: str, last_name: str):
    """Send notification to admin about activation request."""
    name = first_name
    if last_name:
        name += f" {last_name}"
    if username:
        name += f" (@{username})"

    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"🔔 **Bot Activation Request**\n\n"
                f"📋 Chat: {escape_markdown(chat_title)} (ID: `{chat_id}`)\n"
                f"👤 Requested by: {escape_markdown(name)} (ID: `{user_id}`)\n\n"
                f"Use /approve_activation {chat_id} to approve or /deny_activation {chat_id} to deny."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin of activation request: {e}")


def escape_markdown(text: str) -> str:
    """Escape special Markdown characters."""
    if not text:
        return text
    escape_chars = r'\_`['
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /activate command.
    
    - Moderators/admins can activate directly
    - Non-moderators trigger an activation request to admin
    """
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or f"Chat {chat_id}"
    
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name or "Unknown"
    last_name = update.effective_user.last_name

    # If already activated, inform user
    if is_activated(chat_id):
        return

    # Check if user is a moderator or admin
    if can_moderate_chat(update):
        ACTIVATED_CHATS.add(chat_id)
        save_activated_chats(ACTIVATED_CHATS)
        await update.message.reply_text("✅ Activated.")
        return

    # Non-moderator: create activation request
    if has_pending_activation_request(chat_id):
        await update.message.reply_text(
            "⏳ Activation pending."
        )
        return

    # Create activation request
    request = {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "status": "pending"
    }
    ACTIVATION_REQUESTS.append(request)
    save_activation_requests(ACTIVATION_REQUESTS)

    await update.message.reply_text(
        "📝 Activation request submitted. Admin will be notified."
    )

    # Notify admin
    await notify_admin_of_activation_request(
        update, context, chat_id, chat_title, 
        user_id, username, first_name, last_name
    )


async def approve_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve_activation command - admin approves chat activation."""
    if update.effective_user.id != ADMIN_USER_ID:
        return

    if not context.args:
        await update.message.reply_text("❌ Please provide chat ID.\nUsage: /approve_activation <chat_id>")
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID.")
        return

    # Activate the chat
    ACTIVATED_CHATS.add(chat_id)
    save_activated_chats(ACTIVATED_CHATS)

    # Update request status
    for req in ACTIVATION_REQUESTS:
        if req["chat_id"] == chat_id and req["status"] == "pending":
            req["status"] = "approved"
            break
    save_activation_requests(ACTIVATION_REQUESTS)

    await update.message.reply_text(f"✅ Bot activated for `{chat_id}`.", parse_mode="Markdown")

    # Notify the requester
    for req in ACTIVATION_REQUESTS:
        if req["chat_id"] == chat_id and req["status"] == "approved" and req["user_id"]:
            try:
                await context.bot.send_message(
                    chat_id=req["user_id"],
                    text=(
                        f"🎉 **Your activation request has been approved!**\n\n"
                        f"The bot is now active in **{escape_markdown(req['chat_title'])}**.\n\n"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify user of activation approval: {e}")
            break


async def deny_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /deny_activation command - admin denies chat activation."""
    if update.effective_user.id != ADMIN_USER_ID:
        return

    if not context.args:
        await update.message.reply_text("❌ Please provide chat ID.\nUsage: /deny_activation <chat_id>")
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID.")
        return

    # Update request status
    user_id = None
    for req in ACTIVATION_REQUESTS:
        if req["chat_id"] == chat_id and req["status"] == "pending":
            req["status"] = "denied"
            user_id = req["user_id"]
            break
    save_activation_requests(ACTIVATION_REQUESTS)

    await update.message.reply_text(f"⛔ Activation request for chat ID `{chat_id}` has been denied.", parse_mode="Markdown")

    # Notify the requester
    if user_id:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Activation not approved. Contact the admin."
            )
        except Exception as e:
            logger.error(f"Failed to notify user of activation denial: {e}")


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if not can_moderate_chat(update):
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


async def list_activation_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List pending activation requests (admin only)."""
    if update.effective_user.id != ADMIN_USER_ID:
        return

    pending = [req for req in ACTIVATION_REQUESTS if req["status"] == "pending"]
    
    if not pending:
        await update.message.reply_text("✅ No pending activation requests.")
        return

    text = "📋 **Pending Activation Requests:**\n\n"
    for req in pending:
        name = req["first_name"]
        if req.get("last_name"):
            name += f" {req['last_name']}"
        if req.get("username"):
            name += f" (@{req['username']})"
        
        text += f"📋 Chat: {escape_markdown(req.get('chat_title', 'Unknown'))} (ID: `{req['chat_id']}`)\n"
        text += f"👤 Requested by: {escape_markdown(name)} (ID: `{req['user_id']}`)\n\n"

    text += "Use /approve_activation <chat_id> or /deny_activation <chat_id>"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def doorman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle doorman mode for the current chat - auto-deletes join/leave system messages."""
    chat_id = update.effective_chat.id

    if not can_moderate_chat(update):
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