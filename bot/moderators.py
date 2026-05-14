# bot/moderators.py
"""
Moderator management system for the Telegram bot.
Handles moderator permissions, access requests, and related commands.
"""

import json
import os
import re
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .config import logger
from .utils import extract_social_urls


# File paths for data persistence
MODERATORS_FILE = "/data/moderators.json"
ACCESS_REQUESTS_FILE = "/data/access_requests.json"
SETTINGS_FILE = "/data/settings.json"

# In-memory storage
moderators: dict[int, set[int]] = {}  # {moderator_user_id: {chat_id, ...}}
access_requests: list[dict] = []  # [{user_id, username, first_name, last_name, status}, ...]
settings: dict = {"access_requests_enabled": True}


def load_moderators() -> dict[int, set[int]]:
    """Load moderators from file."""
    if not os.path.exists(MODERATORS_FILE):
        return {}
    try:
        with open(MODERATORS_FILE, "r") as f:
            data = json.load(f)
            # Convert to {user_id: set(chat_ids)}
            return {int(uid): set(chats) for uid, chats in data.items()}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to load moderators: {e}")
        return {}


def save_moderators() -> None:
    """Save moderators to file."""
    # Convert sets to lists for JSON serialization
    data = {str(uid): list(chats) for uid, chats in moderators.items()}
    with open(MODERATORS_FILE, "w") as f:
        json.dump(data, f)


def load_access_requests() -> list[dict]:
    """Load access requests from file."""
    if not os.path.exists(ACCESS_REQUESTS_FILE):
        return []
    try:
        with open(ACCESS_REQUESTS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to load access requests: {e}")
        return []


def save_access_requests() -> None:
    """Save access requests to file."""
    with open(ACCESS_REQUESTS_FILE, "w") as f:
        json.dump(access_requests, f)


def load_settings() -> dict:
    """Load settings from file."""
    if not os.path.exists(SETTINGS_FILE):
        return {"access_requests_enabled": True}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to load settings: {e}")
        return {"access_requests_enabled": True}


def save_settings() -> None:
    """Save settings to file."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)


# Initialize storage from files
moderators = load_moderators()
access_requests = load_access_requests()
settings = load_settings()


def is_admin(update: Update) -> bool:
    """Check if the user is the bot admin."""
    from .config import os
    admin_id = os.getenv("ADMIN_USER_ID")
    if not admin_id:
        return False
    return update.effective_user and update.effective_user.id == int(admin_id)


def is_moderator(user_id: int) -> bool:
    """Check if a user is a moderator."""
    return user_id in moderators


def add_moderator(user_id: int) -> None:
    """Add a user as moderator."""
    moderators[user_id] = set()
    save_moderators()


def remove_moderator(user_id: int) -> None:
    """Remove a user as moderator."""
    if user_id in moderators:
        del moderators[user_id]
        save_moderators()


def has_pending_request(user_id: int) -> bool:
    """Check if a user has a pending access request."""
    return any(
        req["user_id"] == user_id and req["status"] == "pending"
        for req in access_requests
    )


def create_access_request(user_id: int, username: Optional[str], first_name: str, last_name: Optional[str]) -> bool:
    """Create a new access request."""
    if has_pending_request(user_id):
        return False
    
    request = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "status": "pending"
    }
    access_requests.append(request)
    save_access_requests()
    return True


def get_pending_requests() -> list[dict]:
    """Get all pending access requests."""
    return [req for req in access_requests if req["status"] == "pending"]


def approve_request(user_id: int) -> bool:
    """Approve an access request and add user as moderator."""
    for req in access_requests:
        if req["user_id"] == user_id and req["status"] == "pending":
            req["status"] = "approved"
            # Add as moderator
            add_moderator(user_id)
            save_access_requests()
            return True
    return False


def deny_request(user_id: int) -> bool:
    """Deny an access request."""
    for req in access_requests:
        if req["user_id"] == user_id and req["status"] == "pending":
            req["status"] = "denied"
            save_access_requests()
            return True
    return False


# Command handlers

async def access_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /access command - users request moderator access."""
    if not update.effective_user:
        return
    
    if not settings.get("access_requests_enabled", True):
        await update.message.reply_text(
            "❗ Contact the admin for moderator access."
        )
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name or "Unknown"
    last_name = update.effective_user.last_name
    
    # Check if already a moderator
    if user_id in moderators and moderators[user_id]:
        await update.message.reply_text(
            "✅ You are already a moderator! You can use /help to see your available commands."
        )
        return
    
    # Check for pending request
    if has_pending_request(user_id):
        return
    
    # Create access request
    create_access_request(user_id, username, first_name, last_name)
    
    await update.message.reply_text(
        "✅ Your access request has been submitted! You will be notified once the admin reviews it."
    )
    
    # Notify admin
    await notify_admin_of_request(update, context, user_id, username, first_name, last_name)


async def notify_admin_of_request(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   user_id: int, username: Optional[str], 
                                   first_name: str, last_name: Optional[str]):
    """Send notification to admin about new access request."""
    from .config import os
    admin_id = os.getenv("ADMIN_USER_ID")
    if not admin_id:
        return
    
    name = escape_markdown(first_name)
    if last_name:
        name += f" {escape_markdown(last_name)}"
    if username:
        name += f" (@{escape_markdown(username)})"
    
    try:
        await context.bot.send_message(
            chat_id=int(admin_id),
            text=(
                f"🔔 **New Moderator Access Request**\n\n"
                f"👤 User: {name}\n"
                f"🆔 User ID: `{user_id}`\n\n"
                f"Use /approve to grant access or /deny to reject."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command - admin approves access request."""
    if not is_admin(update):
        return
    
    # Check if replying to a message or if user_id is provided
    user_id = None
    
    if update.message.reply_to_message:
        # Try to extract user_id from the original request notification
        reply_text = update.message.reply_to_message.text
        if reply_text:
            # Look for User ID in the message - try multiple patterns for robustness
            # Pattern 1: User ID: `12345` (with backticks)
            match = re.search(r'User ID:\s*`?(\d+)`?', reply_text)
            if not match:
                # Pattern 2: ID: `12345` or ID: 12345
                match = re.search(r'ID:\s*`?(\d+)`?', reply_text)
            if not match:
                # Pattern 3: Any standalone number that looks like a user ID (5+ digits)
                match = re.search(r'\b(\d{5,})\b', reply_text)
            if match:
                user_id = int(match.group(1))
    
    if not user_id and context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            pass
    
    if not user_id:
        await update.message.reply_text(
            "❌ Please reply to the access request message or provide user ID.\n"
            "Usage: /approve <user_id> or reply to request message"
        )
        return
    
    if approve_request(user_id):
        await update.message.reply_text(f"✅ User {user_id} has been approved as moderator!")
        
        # Notify the approved user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 **Your moderator access has been approved!**\n\n"
                    "You can now activate/deactivate the bot in your chats and manage doorman settings.\n\n"
                    "Available commands:\n"
                    "/activate - Activate bot for current chat\n"
                    "/deactivate - Deactivate bot for current chat\n"
                    "/doorman - Toggle doorman mode (auto-delete join/leave messages)\n"
                    "/myChats - List chats you control\n"
                    "/help - Show all available commands"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify approved user: {e}")
    else:
        await update.message.reply_text(
            f"❌ No pending request found for user {user_id}."
        )


async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /deny command - admin denies access request."""
    if not is_admin(update):
        return
    
    user_id = None
    
    if update.message.reply_to_message:
        reply_text = update.message.reply_to_message.text
        if reply_text:
            # Look for User ID in the message - try multiple patterns for robustness
            # Pattern 1: User ID: `12345` (with backticks)
            match = re.search(r'User ID:\s*`?(\d+)`?', reply_text)
            if not match:
                # Pattern 2: ID: `12345` or ID: 12345
                match = re.search(r'ID:\s*`?(\d+)`?', reply_text)
            if not match:
                # Pattern 3: Any standalone number that looks like a user ID (5+ digits)
                match = re.search(r'\b(\d{5,})\b', reply_text)
            if match:
                user_id = int(match.group(1))
    
    if not user_id and context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            pass
    
    if not user_id:
        await update.message.reply_text(
            "❌ Please reply to the access request message or provide user ID.\n"
            "Usage: /deny <user_id> or reply to request message"
        )
        return
    
    if deny_request(user_id):
        await update.message.reply_text(f"⛔ Access request from user {user_id} has been denied.")
        
        # Notify the denied user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Your moderator access request has been denied by the admin."
            )
        except Exception as e:
            logger.error(f"Failed to notify denied user: {e}")
    else:
        await update.message.reply_text(
            f"❌ No pending request found for user {user_id}."
        )


async def access_enabled_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /access_enabled command - admin enables access requests."""
    if not is_admin(update):
        return
    
    settings["access_requests_enabled"] = True
    save_settings()
    
    await update.message.reply_text(
        "✅ Access requests are now **enabled**. Users can use /access to request moderator access.",
        parse_mode="Markdown"
    )


async def access_disabled_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /access_disabled command - admin disables access requests."""
    if not is_admin(update):
        return
    
    settings["access_requests_enabled"] = False
    save_settings()
    
    await update.message.reply_text(
        "⛔ Access requests are now **disabled**. Users cannot request moderator access.",
        parse_mode="Markdown"
    )


async def add_moderator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addmod command - admin adds moderator manually by username or user ID."""
    if not is_admin(update):
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide a username or user ID.\n"
            "Usage: /addmod @username OR /addmod <user_id>"
        )
        return
    
    user_arg = context.args[0]
    user_id = None
    username = None
    
    # Check if the argument is a numeric user ID or a username
    try:
        user_id = int(user_arg)
    except ValueError:
        # Not a number, treat as username
        if user_arg.startswith('@'):
            username = user_arg[1:]
        else:
            username = user_arg
    
    # If we have a username, try to resolve it to get user_id
    if username is not None:
        try:
            chat = await context.bot.get_chat(f"@{username}")
            user_id = chat.id
        except Exception as e:
            # Try Telethon as fallback
            logger.debug(f"Failed to resolve username @{username} via bot API, trying Telethon...")
            try:
                from .telethon_client import resolve_username
                result = await resolve_username(username)
                if result:
                    user_id, first_name, resolved_username = result
                else:
                    raise Exception("Not found via Telethon")
            except Exception as telethon_error:
                logger.error(f"Failed to resolve username @{username} via Telethon: {telethon_error}")
                await update.message.reply_text(
                    f"❌ Could not find user @{escape_markdown(username)}. This usually means:\n"
                    f"1. The username is incorrect\n"
                    f"2. The user account doesn't exist\n\n"
                    f"**Note:** Configure TELEGRAM_API_ID and TELEGRAM_API_HASH to resolve usernames without bot interaction.\n"
                    f"Or use /addmod <user_id> if you know their numeric Telegram ID."
                )
                return
    
    # Now we should have a user_id
    if user_id is None:
        await update.message.reply_text("❌ Could not determine user ID.")
        return
    
    # Add as moderator
    display_name = f"@{escape_markdown(username)}" if username else f"User ID `{user_id}`"
    add_moderator(user_id)
    await update.message.reply_text(
        f"✅ {display_name} (ID: `{user_id}`) has been added as a moderator.\n\n"
        f"They can now activate the bot in any chat they are a member of.",
        parse_mode="Markdown"
    )
    
    # Notify the new moderator
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 **You have been added as a moderator!**\n\n"
                f"You can now manage the bot in any chat you are a member of.\n\n"
                "Available commands:\n"
                "/activate - Activate bot for current chat\n"
                "/deactivate - Deactivate bot for current chat\n"
                "/doorman - Toggle doorman mode\n"
                "/myChats - List chats you moderate\n"
                "/help - Show all available commands"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify new moderator: {e}")


async def remove_moderator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removemod command - admin removes moderator by username or user ID."""
    if not is_admin(update):
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide a username or user ID.\n"
            "Usage: /removemod @username OR /removemod <user_id>"
        )
        return
    
    user_arg = context.args[0]
    user_id = None
    username = None
    
    # Check if the argument is a numeric user ID or a username
    try:
        user_id = int(user_arg)
    except ValueError:
        # Not a number, treat as username
        if user_arg.startswith('@'):
            username = user_arg[1:]
        else:
            username = user_arg
    
    # If we have a username, try to resolve it to get user_id
    if username is not None:
        try:
            chat = await context.bot.get_chat(f"@{username}")
            user_id = chat.id
        except Exception as e:
            logger.error(f"Failed to resolve username @{username}: {e}")
            await update.message.reply_text(
                f"❌ Could not find user @{escape_markdown(username)}. Make sure the username is correct and the user has interacted with the bot.",
                parse_mode="Markdown"
            )
            return
    
    # Now we should have a user_id
    if user_id is None:
        await update.message.reply_text("❌ Could not determine user ID.")
        return
    
    # Remove moderator
    display_name = f"@{escape_markdown(username)}" if username else f"User ID `{user_id}`"
    remove_moderator(user_id)
    await update.message.reply_text(
        f"✅ {display_name} (ID: `{user_id}`) has been removed as a moderator.",
        parse_mode="Markdown"
    )
    
    # Notify the removed moderator
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ **Moderator Update**\n\n"
                f"Your moderator access has been removed by the admin."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify removed moderator: {e}")


def escape_markdown(text: str) -> str:
    """Escape special Markdown characters in user-provided text."""
    if not text:
        return text
    # Escape characters that have special meaning in Markdown
    escape_chars = r'\_`['
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def list_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /requests command - admin views pending requests."""
    if not is_admin(update):
        return
    
    pending = get_pending_requests()
    
    if not pending:
        await update.message.reply_text("✅ No pending access requests.")
        return
    
    text = "📋 **Pending Access Requests:**\n\n"
    for req in pending:
        name = escape_markdown(req["first_name"])
        if req.get("last_name"):
            name += f" {escape_markdown(req['last_name'])}"
        if req.get("username"):
            name += f" (@{escape_markdown(req['username'])})"
        
        text += f"👤 {name} (ID: `{req['user_id']}`)\n"
    
    text += "\nUse /approve <user_id> or /deny <user_id>"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def list_moderators_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listmods command - admin views all moderators."""
    if not is_admin(update):
        return
    
    if not moderators:
        await update.message.reply_text("✅ No moderators configured.")
        return
    
    text = "👥 **Current Moderators:**\n\n"
    
    for user_id in sorted(moderators.keys()):
        # Try to get user info for display
        try:
            user = await context.bot.get_chat(user_id)
            name = escape_markdown(user.first_name) or "Unknown"
            if user.last_name:
                name += f" {escape_markdown(user.last_name)}"
            
            # Create profile link
            if user.username:
                profile_link = f"@{escape_markdown(user.username)}"
            else:
                profile_link = f"[profile](tg://user?id={user_id})"
            
            text += f"👤 {name} ({profile_link}) - ID: `{user_id}`\n"
        except Exception as e:
            logger.debug(f"Could not get info for user {user_id}: {e}")
            text += f"👤 User ID: `{user_id}`\n"
    
    text += f"\n**Total:** {len(moderators)} moderator(s)"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def my_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /myChats command - moderators view their status."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if is_moderator(user_id):
        await update.message.reply_text(
            "✅ You are a moderator. You can activate/deactivate the bot in any chat you are a member of.\n\n"
            "Use /activate in any group to enable the bot there."
        )
    elif is_admin(update):
        await update.message.reply_text(
            "As admin, you have access to all chats. Use /listChats to see all activated chats."
        )
    else:
        await update.message.reply_text(
            "❌ You are not a moderator. Use /access to request moderator access."
        )


async def load_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /load command - admin can reply to a message with links to download content."""
    if not is_admin(update):
        return
    
    if not update.message or not update.message.reply_to_message:
        return
    
    replied_message = update.message.reply_to_message
    if not replied_message.text:
        return
    
    urls = extract_social_urls(replied_message.text)
    if not urls:
        return
    
    # Import here to avoid circular imports
    from .handlers import handle_message
    await handle_message(urls, update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command - show available commands."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    is_mod = user_id in moderators and moderators[user_id]
    admin = is_admin(update)
    
    text = "🤖 **Bot Commands Help**\n\n"
    
    if admin:
        text += "**Admin Commands:**\n"
        text += "/activate - Activate bot for current chat\n"
        text += "/deactivate - Deactivate bot for current chat\n"
        text += "/doorman - Toggle doorman mode (auto-delete join/leave messages)\n"
        text += "/listChats - List all activated chats\n"
        text += "/activation_requests - View pending bot activation requests\n"
        text += "/approve_activation <chat_id> - Approve bot activation for a chat\n"
        text += "/deny_activation <chat_id> - Deny bot activation for a chat\n"
        text += "/listmods - List all moderators with profile links\n"
        text += "/approve <user_id> - Approve moderator access request\n"
        text += "/deny <user_id> - Deny moderator access request\n"
        text += "/requests - View pending moderator access requests\n"
        text += "/access_enabled - Enable access requests\n"
        text += "/access_disabled - Disable access requests\n"
        text += "/addmod @username - Add moderator\n"
        text += "/removemod @username - Remove moderator\n"
        text += "/load - Reply to a message with links to download content (works in any chat)\n\n"
    elif is_mod:
        text += "**Moderator Commands:**\n"
        text += "/activate - Activate bot for current chat\n"
        text += "/deactivate - Deactivate bot for current chat\n"
        text += "/doorman - Toggle doorman mode\n"
        text += "/myChats - Check your moderator status\n"
        text += "/help - Show this help message\n\n"
    else:
        text += "**Available Commands:**\n"
        text += "/access - Request moderator access\n"
        text += "/help - Show this help message\n\n"
    
    text += "**Bot Description:**\n"
    text += "This bot downloads and shares Instagram/Facebook media in Telegram chats.\n"
    text += "Moderators can activate the bot in their chats and manage doorman settings.\n"
    text += "Simply send Instagram/Facebook links in an activated chat to download media."
    
    await update.message.reply_text(text, parse_mode="Markdown")