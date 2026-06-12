# bot/telethon_client.py
"""
Telethon client for resolving usernames, getting chat information, and uploading large files.
This allows the bot to resolve any public username without requiring prior interaction,
and upload large files via user account to bypass bot file size limits.
"""

import os
import asyncio
from typing import Optional, Tuple

from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel

from .config import logger

# Environment variables for Telethon
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

# Global client instance
_client: Optional[TelegramClient] = None
_client_initialized = False


def get_telethon_client() -> Optional[TelegramClient]:
    """Get the Telethon client instance if configured."""
    global _client, _client_initialized
    
    if _client_initialized:
        return _client
    
    if not API_ID or not API_HASH:
        logger.warning("TELEGRAM_API_ID and TELEGRAM_API_HASH not set. Telethon features disabled.")
        _client_initialized = True
        return None
    
    try:
        if SESSION_STRING:
            # Use existing session string
            _client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        else:
            # Create new session (will need to be authenticated)
            _client = TelegramClient('bot_session', API_ID, API_HASH)
        
        _client.start()
        _client_initialized = True
        logger.info("Telethon client initialized successfully")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize Telethon client: {e}")
        _client_initialized = True
        return None


async def resolve_username(username: str) -> Optional[Tuple[int, str, str]]:
    """
    Resolve a username to user ID and name using Telethon.
    Returns (user_id, first_name, username) or None if not found.
    """
    client = get_telethon_client()
    if not client:
        return None
    
    try:
        # Ensure client is connected
        if not client.is_connected():
            await client.connect()
        
        entity = await client.get_entity(username)
        
        if isinstance(entity, User):
            return (entity.id, entity.first_name or "", entity.username or "")
        elif isinstance(entity, (Chat, Channel)):
            return (entity.id, entity.title or "", getattr(entity, 'username', None) or "")
        
        return None
    except Exception as e:
        logger.debug(f"Failed to resolve username {username} via Telethon: {e}")
        return None


async def get_chat_info(chat_id: int) -> Optional[dict]:
    """
    Get chat information using Telethon.
    Returns dict with 'title', 'username', 'link' or None if not found.
    """
    client = get_telethon_client()
    if not client:
        return None
    
    try:
        # Ensure client is connected
        if not client.is_connected():
            await client.connect()
        
        entity = await client.get_entity(chat_id)
        
        result = {
            'title': entity.title if hasattr(entity, 'title') else "",
            'username': getattr(entity, 'username', None),
            'link': None
        }
        
        # Generate link
        if result['username']:
            result['link'] = f"https://t.me/{result['username']}"
        elif isinstance(entity, User):
            result['link'] = f"tg://user?id={entity.id}"
        elif isinstance(entity, (Chat, Channel)):
            # For private chats, try to get invite link
            try:
                invite = await client(ExportChatInviteRequest(entity.id))
                result['link'] = invite.link
            except Exception:
                result['link'] = None
        
        return result
    except Exception as e:
        logger.debug(f"Failed to get chat info for {chat_id} via Telethon: {e}")
        return None


async def upload_to_admin_chat(file_path: str, chat_id: int, status_msg_id: int, original_reply_to_message_id: int) -> Optional[int]:
    """
    Upload a file to the admin's chat using the user account.
    The admin will then forward this to the bot, which will send it as its own message.
    
    Caption format: "{chat_id}-{status_msg_id}-{original_reply_to_message_id}-{file_name}"
    This allows the bot to identify the target chat and status message to clean up.
    
    Args:
        file_path: Path to the file to upload
        chat_id: Target chat ID where the bot should send the file
        status_msg_id: Message ID of the status message (for cleanup)
        original_reply_to_message_id: Message ID of the original reply-to message
    
    Returns:
        Message ID of the uploaded file in admin's chat, or None if failed
    """
    client = get_telethon_client()
    if not client:
        logger.error("Telethon client not available for file upload")
        return None
    
    try:
        # Ensure client is connected
        if not client.is_connected():
            await client.connect()
        
        # Get admin's chat
        admin_entity = await client.get_entity('@group_insta_loader_bot')  # The user's own chat (Saved Messages)
        
        # Upload file
        logger.info(f"Uploading file to admin chat: {file_path}")
        
        # Get file name for caption
        file_name = os.path.basename(file_path)
        
        # Caption format: chat_id-status_msg_id-original_reply_to_message_id-file_name
        caption = f"{chat_id}-{status_msg_id}-{original_reply_to_message_id}-{file_name}"
        
        # Upload file (type doesn't matter for caption, use generic send_file)
        message = await client.send_file(
            admin_entity,
            file_path,
            caption=caption,
            progress_callback=upload_progress_callback
        )
        
        logger.info(f"✅ File uploaded to admin chat: message_id={message.id}, caption={caption}")
        return message.id
        
    except Exception as e:
        logger.error(f"Failed to upload file to admin chat: {e}")
        return None


def upload_progress_callback(current, total):
    """Progress callback for file uploads."""
    percent = (current / total) * 100
    logger.debug(f"Upload progress: {percent:.1f}% ({current}/{total} bytes)")


# StringSession import for Telethon
try:
    from telethon.sessions import StringSession
except ImportError:
    StringSession = None
