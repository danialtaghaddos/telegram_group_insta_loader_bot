# bot/hold_list.py
"""
Hold list (blacklist) management.

Moderators/admin can put a user "on hold" by replying to one of their
messages in a group with /hold. Users on hold have their links ignored
until removed via /unhold.
"""

from contextlib import suppress

from telegram import Update
from telegram.ext import ContextTypes

from .config import logger, ADMIN_USER_ID
from .storage import load_hold_list_from_storage, save_hold_list_to_storage
from .moderators import is_admin, is_moderator, escape_markdown, _resolve_user_id


# In-memory storage
HOLD_LIST: set[int] = set()


def load_hold_list() -> set[int]:
    try:
        data = load_hold_list_from_storage()
        return set(data) if data else set()
    except Exception as e:
        logger.warning(f"Failed to load hold list: {e}")
    return set()


def save_hold_list() -> None:
    try:
        save_hold_list_to_storage(list(HOLD_LIST))
    except Exception as e:
        logger.error(f"Failed to save hold list: {e}")


# Initialize from local files at import time; refreshed from Telegram in on_startup
HOLD_LIST = load_hold_list()


def reload_from_storage() -> None:
    """Reload in-memory state from local files after Telegram sync."""
    global HOLD_LIST
    HOLD_LIST = load_hold_list()


def is_on_hold(user_id: int) -> bool:
    """Check if a user is on the hold list."""
    return user_id in HOLD_LIST


def _display_name(first_name: str, last_name: str | None, username: str | None) -> str:
    name = escape_markdown(first_name or "Unknown")
    if last_name:
        name += f" {escape_markdown(last_name)}"
    if username:
        name += f" (@{escape_markdown(username)})"
    return name


async def _notify_requester_or_admin(context: ContextTypes.DEFAULT_TYPE, requester_id: int, text: str) -> None:
    """Send a report to the moderator who issued the command, falling back to admin."""
    try:
        await context.bot.send_message(chat_id=requester_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Failed to notify requester {requester_id}, falling back to admin: {e}")
        try:
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=text, parse_mode="Markdown")
        except Exception as e2:
            logger.error(f"Failed to notify admin about hold list change: {e2}")


async def hold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /hold command - reply to a user's message in a group to put them on hold."""
    if not update.effective_user or not update.message:
        return

    requester_id = update.effective_user.id
    if not (is_admin(update) or is_moderator(requester_id)):
        return

    chat = update.effective_chat
    replied = update.message.reply_to_message

    with suppress(Exception):
        await update.message.delete()

    if not chat or chat.type not in ("group", "supergroup"):
        return

    if not replied or not replied.from_user:
        return

    target = replied.from_user

    HOLD_LIST.add(target.id)
    save_hold_list()

    name = _display_name(target.first_name, target.last_name, target.username)
    chat_title = escape_markdown(chat.title or f"Chat {chat.id}")

    report = (
        f"🚫 **User added to hold list**\n\n"
        f"👤 {name}\n"
        f"🆔 User ID: `{target.id}`\n"
        f"💬 Chat: {chat_title}\n\n"
        f"Their links will be ignored until removed with /unhold."
    )

    await _notify_requester_or_admin(context, requester_id, report)


async def unhold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unhold command - remove a user from the hold list.

    Usage: reply to the user's message with /unhold, or /unhold <user_id or @username>.
    """
    if not update.effective_user or not update.message:
        return

    requester_id = update.effective_user.id
    if not (is_admin(update) or is_moderator(requester_id)):
        return

    target_id = None
    display = None

    replied = update.message.reply_to_message
    if replied and replied.from_user:
        target_id = replied.from_user.id
        display = _display_name(replied.from_user.first_name, replied.from_user.last_name, replied.from_user.username)
    elif context.args:
        target_id, username = await _resolve_user_id(context, context.args[0])
        if target_id is not None:
            display = f"@{escape_markdown(username)}" if username else f"User ID `{target_id}`"

    if target_id is None:
        await update.message.reply_text(
            "❌ Reply to the user's message with /unhold, or use /unhold <user_id or @username>."
        )
        return

    if target_id not in HOLD_LIST:
        await update.message.reply_text(f"⚠️ User {target_id} is not on the hold list.")
        return

    HOLD_LIST.discard(target_id)
    save_hold_list()

    await update.message.reply_text(
        f"✅ {display or f'User ID `{target_id}`'} has been removed from the hold list.",
        parse_mode="Markdown"
    )


async def hold_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /holdList command - admin views all users on hold."""
    if not is_admin(update):
        return

    if not HOLD_LIST:
        await update.message.reply_text("✅ No users on hold.")
        return

    text = "🚫 **Users On Hold:**\n\n"
    for user_id in sorted(HOLD_LIST):
        try:
            user = await context.bot.get_chat(user_id)
            name = escape_markdown(user.first_name) or "Unknown"
            if user.last_name:
                name += f" {escape_markdown(user.last_name)}"
            profile_link = f"@{escape_markdown(user.username)}" if user.username else f"[profile](tg://user?id={user_id})"
            text += f"👤 {name} ({profile_link}) - ID: `{user_id}`\n"
        except Exception as e:
            logger.debug(f"Could not get info for held user {user_id}: {e}")
            text += f"👤 User ID: `{user_id}`\n"

    text += f"\n**Total:** {len(HOLD_LIST)} user(s)"

    await update.message.reply_text(text, parse_mode="Markdown")
