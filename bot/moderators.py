# bot/moderators.py
"""
Moderator management system for the Telegram bot.
Handles moderator permissions, access requests, and related commands.
"""

import os
import re
from contextlib import suppress
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .config import logger
from .storage import (
    load_moderators_from_storage,
    save_moderators_to_storage,
    load_access_requests_from_storage,
    save_access_requests_to_storage,
)
from .utils import extract_social_urls


# In-memory storage
moderators: dict[int, set[int]] = {}  # {moderator_user_id: {chat_id, ...}}
access_requests: list[dict] = []  # [{user_id, username, first_name, last_name, status}, ...]


def load_moderators() -> dict[int, set[int]]:
    try:
        data = load_moderators_from_storage()
        if data:
            return {uid: set(chats) for uid, chats in data.items()}
    except Exception as e:
        logger.warning(f"Failed to load moderators: {e}")
    return {}


def save_moderators() -> None:
    try:
        save_moderators_to_storage(moderators)
    except Exception as e:
        logger.error(f"Failed to save moderators: {e}")


def load_access_requests() -> list[dict]:
    try:
        data = load_access_requests_from_storage()
        if data:
            return data
    except Exception as e:
        logger.warning(f"Failed to load access requests: {e}")
    return []


def save_access_requests() -> None:
    try:
        save_access_requests_to_storage(access_requests)
    except Exception as e:
        logger.error(f"Failed to save access requests: {e}")


# Initialize from local files at import time; refreshed from Telegram in on_startup
moderators = load_moderators()
access_requests = load_access_requests()


def reload_from_storage() -> None:
    """Reload in-memory state from local files after Telegram sync."""
    global moderators, access_requests
    moderators = load_moderators()
    access_requests = load_access_requests()


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
                    "/doorman - Toggle doorman mode to auto-delete join and leave messages\n"
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

async def _resolve_user_id(context: ContextTypes.DEFAULT_TYPE, user_arg: str) -> tuple[Optional[int], Optional[str]]:
    """Resolve a username or user ID string to a numeric user ID.
    
    Returns:
        Tuple of (user_id, username) or (None, None) if resolution fails.
    """
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
                logger.error(f"Failed to resolve username @{username}: {telethon_error}")
                return None, username
    
    return user_id, username


async def _add_single_moderator(context: ContextTypes.DEFAULT_TYPE, user_arg: str) -> tuple[bool, str]:
    """Add a single moderator by username or user ID.
    
    Returns:
        Tuple of (success, message) where message describes the result.
    """
    user_arg = user_arg.strip()
    if not user_arg:
        return False, "Empty argument"
    
    user_id, username = await _resolve_user_id(context, user_arg)
    
    if user_id is None:
        display = f"@{escape_markdown(username)}" if username else user_arg
        return False, f"❌ Could not find user `{escape_markdown(user_arg)}`"
    
    # Check if already a moderator
    if user_id in moderators:
        display_name = f"@{escape_markdown(username)}" if username else f"User ID `{user_id}`"
        return False, f"⚠️ {display_name} (ID: `{user_id}`) is already a moderator"
    
    # Add as moderator
    add_moderator(user_id)
    display_name = f"@{escape_markdown(username)}" if username else f"User ID `{user_id}`"
    
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
    
    return True, f"✅ {display_name} (ID: `{user_id}`) has been added as a moderator."


async def add_moderator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addMods command - admin adds moderator(s) by username or user ID.
    
    Supports adding multiple moderators at once using comma-separated values.
    Examples:
        /addMods @username
        /addMods 123456789
        /addMods @user1,@user2,123456789
        /addMods @user1 123456789 @user2
    """
    if not is_admin(update):
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide a username or user ID.\n"
            "Usage: /addMods @username OR /addMods <user_id>\n"
            "You can also add multiple moderators at once:\n"
            "/addMods @user1,@user2,123456789"
        )
        return
    
    # Parse all arguments and split by comma for each argument
    all_user_args = []
    for arg in context.args:
        # Split each argument by comma to support comma-separated lists
        parts = [p.strip() for p in arg.split(',') if p.strip()]
        all_user_args.extend(parts)
    
    if not all_user_args:
        await update.message.reply_text(
            "❌ No valid usernames or user IDs provided.\n"
            "Usage: /addMods @username OR /addMods <user_id>\n"
            "You can also add multiple moderators at once:\n"
            "/addMods @user1,@user2,123456789"
        )
        return
    
    # If only one moderator, use the simple single-message format
    if len(all_user_args) == 1:
        success, message = await _add_single_moderator(context, all_user_args[0])
        await update.message.reply_text(
            message + "\n\nThey can now activate the bot in any chat they are a member of." if success else message,
            parse_mode="Markdown"
        )
        return
    
    # For multiple moderators, process all and provide a summary
    results = []
    for user_arg in all_user_args:
        success, message = await _add_single_moderator(context, user_arg)
        results.append((success, message))
    
    # Build summary message
    successful = [msg for success, msg in results if success]
    failed = [msg for success, msg in results if not success]
    
    summary_lines = []
    if successful:
        summary_lines.append(f"✅ **Successfully added {len(successful)} moderator(s):**")
        summary_lines.extend(successful)
    if failed:
        summary_lines.append(f"\n❌ **Failed to add {len(failed)} user(s):**")
        summary_lines.extend(failed)
    
    summary_text = "\n".join(summary_lines)
    await update.message.reply_text(summary_text, parse_mode="Markdown")


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
    
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send help message with Markdown: {e}")
        await update.message.reply_text(text)


async def list_moderators_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listMods command - admin views all moderators."""
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
    if not is_admin(update) and not is_moderator(update.effective_user.id):
        return

    if not update.message or not update.message.reply_to_message:
        return
    
    replied_message = update.message.reply_to_message
    if not replied_message.text:
        return
    
    urls = extract_social_urls(replied_message.text)
    if not urls:
        return

    with suppress(Exception):
        await update.message.delete()

    # Import here to avoid circular imports
    from .handlers import handle_message
    await handle_message(urls, update, context, reply_to_message_id=replied_message.message_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command - show available commands."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    is_mod = user_id in moderators and moderators[user_id]
    admin = is_admin(update)
    
    text = "🤖 <b>Bot Commands Help</b>\n\n"
    
    if admin:
        text += "<b>Admin Commands:</b>\n"
        text += "/activate - Activate bot for current chat\n"
        text += "/deactivate - Deactivate bot for current chat\n"
        text += "/doorman - Toggle doorman mode to auto-delete join and leave messages\n"
        text += "/listChats - List all activated chats\n"
        text += "/listMods - List all moderators with profile links\n"
        text += "/approve user_id - Approve moderator access request\n"
        text += "/deny user_id - Deny moderator access request\n"
        text += "/requests - View pending moderator access requests\n"
        text += "/addMods @username - Add moderator (supports multiple: @u1,@u2,123)\n"
        text += "/removemod @username - Remove moderator\n"
        text += "/load - Reply to a message with links to download content, works in any chat\n\n"
    elif is_mod:
        text += "<b>Moderator Commands:</b>\n"
        text += "/activate - Activate bot for current chat\n"
        text += "/deactivate - Deactivate bot for current chat\n"
        text += "/doorman - Toggle doorman mode\n"
        text += "/myChats - Check your moderator status\n"
        text += "/help - Show this help message\n\n"
    else:
        text += "<b>Available Commands:</b>\n"
        text += "/access - Request moderator access\n"
        text += "/help - Show this help message\n\n"
    
    text += "<b>Bot Description:</b>\n"
    text += "This bot downloads and shares media in Telegram chats.\n"
    text += "Moderators can activate the bot in their chats and manage doorman settings.\n\n"
    text += "<b>Supported Platforms:</b>\n"
    text += "• Instagram - Photos and videos\n"
    text += "• Facebook - Videos\n"
    text += "• YouTube - Audio: MP3 or M4A\n\n"
    text += "Simply send links in an activated chat to download media."
    
    try:
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send help message with HTML: {e}")
        await update.message.reply_text(text)
