# bot/telethon_client.py
"""
Telethon client for resolving usernames, getting chat information, and uploading large files.
This allows the bot to resolve any public username without requiring prior interaction,
and upload large files via user account to bypass bot file size limits.
"""

import os
import asyncio
from contextlib import suppress
from typing import Optional, Tuple

from telethon import TelegramClient, helpers
from telethon.errors import FloodWaitError
from telethon.network import MTProtoSender
from telethon.tl import functions, types as tl_types
from telethon.tl.types import User, Chat, Channel
from telethon.client.uploads import UploadMethods as _UploadMethods

from .config import logger, TELETHON_UPLOAD_WORKERS, TELETHON_UPLOAD_CONNECTIONS, UploadCancelledError

# Environment variables for Telethon
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

# Global client instance
_client: Optional[TelegramClient] = None
_client_initialized = False

# Files at or below this size keep using Telethon's original sequential
# upload_file() — not worth the added complexity for small/fast transfers.
_PARALLEL_UPLOAD_MIN_BYTES = 10 * 1024 * 1024
_PARALLEL_UPLOAD_PART_SIZE = 512 * 1024  # Telegram's max part size

if hasattr(os, "pread"):
    _pread = os.pread
else:
    # os.pread is POSIX-only. Production runs on Linux (Proxmox LXC), but
    # fall back to a lock-serialized lseek+read for local Windows testing —
    # correct (not truly parallel disk I/O) since Windows has no atomic
    # positional read.
    import threading
    _pread_fallback_lock = threading.Lock()

    def _pread(fd, length, offset):
        with _pread_fallback_lock:
            os.lseek(fd, offset, os.SEEK_SET)
            return os.read(fd, length)


async def _open_extra_senders(client: TelegramClient, count: int) -> list:
    """Open `count` additional MTProto TCP connections to the client's home
    datacenter, reusing the session's existing auth_key directly (skipping
    key negotiation — see MTProtoSender.__init__/connect: it only generates
    a new key if none is provided). This is deliberately NOT the cross-DC
    `_create_exported_sender`/`_borrow_exported_sender` mechanism: that uses
    auth.ExportAuthorization/ImportAuthorization, which only works for a DC
    *different* from the one you're already connected to — attempting it for
    your own home DC raises DcIdInvalidError (confirmed by reading Telethon's
    own CDN download code, which explicitly special-cases and skips export
    for the home DC). Reusing the auth_key directly works because MTProto's
    auth_key is valid for any connection to the DC it was negotiated with,
    not tied to a specific TCP socket.

    Best-effort: returns however many connections actually succeeded (may be
    fewer than requested, or empty), so callers should fall back gracefully.
    """
    senders = []
    for _ in range(count):
        try:
            sender = MTProtoSender(client.session.auth_key, loggers=client._log)
            await sender.connect(client._connection(
                client.session.server_address,
                client.session.port,
                client.session.dc_id,
                loggers=client._log,
                proxy=client._proxy,
                local_addr=client._local_addr,
            ))
            senders.append(sender)
        except Exception as e:
            logger.warning(f"Failed to open extra upload connection {len(senders) + 1}/{count}: {e}")
            break
    return senders


async def _parallel_upload_file(
    self: TelegramClient,
    file,
    *,
    part_size_kb: float = None,
    file_size: int = None,
    file_name: str = None,
    use_cache=None,
    key: bytes = None,
    iv: bytes = None,
    progress_callback=None,
):
    """Drop-in replacement for Telethon's UploadMethods.upload_file that
    uploads large on-disk files over several *separate* MTProto connections
    at once, instead of Telethon's default strictly-sequential one-at-a-time
    loop over a single connection (the dominant bottleneck for large file
    uploads). Pipelining multiple requests over one connection alone plateaus
    (validated empirically: no gain going from 8 to 16 in-flight requests on
    one connection) since it's still bound by that single TCP flow — this
    spreads chunks across genuinely independent connections instead.

    Falls back to the original sequential implementation for anything that
    isn't a plain large on-disk file (streams/bytes, small files, or
    encrypted secret-chat uploads), so only the slow path is touched.
    """
    is_path = isinstance(file, str) and os.path.isfile(file)
    resolved_size = file_size or (os.path.getsize(file) if is_path else None)

    if not is_path or key or iv or (resolved_size or 0) <= _PARALLEL_UPLOAD_MIN_BYTES:
        return await _UploadMethods.upload_file(
            self, file, part_size_kb=part_size_kb, file_size=file_size,
            file_name=file_name, use_cache=use_cache, key=key, iv=iv,
            progress_callback=progress_callback,
        )

    part_size = _PARALLEL_UPLOAD_PART_SIZE
    part_count = (resolved_size + part_size - 1) // part_size
    file_id = helpers.generate_random_long()
    resolved_name = file_name or os.path.basename(file)

    extra_senders = await _open_extra_senders(self, max(0, TELETHON_UPLOAD_CONNECTIONS - 1))
    # Always include the main connection as one pool member, so we still
    # make progress even if every extra connection attempt failed.
    pool = [self._sender] + extra_senders

    logger.info(
        f"Parallel-uploading {resolved_name} ({resolved_size} bytes, "
        f"{part_count} parts, {len(pool)} connections x {TELETHON_UPLOAD_WORKERS} workers each)"
    )

    fd = os.open(file, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    sent = 0
    sent_lock = asyncio.Lock()
    # One semaphore per connection, so total in-flight = len(pool) * TELETHON_UPLOAD_WORKERS,
    # while each individual connection stays at the depth already validated as stable.
    sems = [asyncio.Semaphore(TELETHON_UPLOAD_WORKERS) for _ in pool]
    flood_waits = []
    slow_requests = []  # (part_index, seconds) for requests that took unusually long —
    # a proxy signal for flood-control sleeps Telethon retries transparently
    # below its default flood_sleep_threshold (60s), which never reach the
    # `except FloodWaitError` below.
    start_time = asyncio.get_event_loop().time()

    async def upload_part(part_index: int):
        nonlocal sent
        pool_index = part_index % len(pool)
        sender = pool[pool_index]
        sem = sems[pool_index]
        offset = part_index * part_size
        async with sem:
            part = await asyncio.to_thread(_pread, fd, part_size, offset)
            req_start = asyncio.get_event_loop().time()
            while True:
                try:
                    ok = await self._call(sender, functions.upload.SaveBigFilePartRequest(
                        file_id, part_index, part_count, part))
                    break
                except FloodWaitError as e:
                    flood_waits.append(e.seconds)
                    logger.warning(
                        f"FloodWait {e.seconds}s on part {part_index} "
                        f"({len(flood_waits)} flood waits so far)"
                    )
                    await asyncio.sleep(e.seconds)
            req_elapsed = asyncio.get_event_loop().time() - req_start
            if req_elapsed > 2:
                slow_requests.append((part_index, req_elapsed))
            if not ok:
                raise RuntimeError(f"Failed to upload file part {part_index}.")
        async with sent_lock:
            sent += len(part)
            if progress_callback:
                await helpers._maybe_await(progress_callback(sent, resolved_size))

    tasks = [asyncio.ensure_future(upload_part(i)) for i in range(part_count)]
    try:
        # FIRST_EXCEPTION (rather than plain gather) lets a raised exception —
        # notably UploadCancelledError from the progress callback — abort the
        # transfer promptly instead of waiting for every in-flight part to finish.
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        if pending:
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            exc = t.exception()
            if exc:
                raise exc
    finally:
        os.close(fd)
        for sender in extra_senders:
            with suppress(Exception):
                await sender.disconnect()

    if slow_requests:
        logger.warning(
            f"{len(slow_requests)}/{part_count} parts took >2s "
            f"(likely internal flood-wait sleeps below the 60s threshold); "
            f"slowest: {max(s for _, s in slow_requests):.1f}s"
        )

    elapsed = asyncio.get_event_loop().time() - start_time
    throughput_kbs = (resolved_size / 1024) / elapsed if elapsed else 0
    logger.info(
        f"Parallel upload of {resolved_name} finished in {elapsed:.1f}s "
        f"({throughput_kbs:.0f} KB/s) over {len(pool)} connections, "
        f"{len(flood_waits)} flood waits (total {sum(flood_waits):.1f}s slept)"
    )

    return tl_types.InputFileBig(file_id, part_count, resolved_name)


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
        _client.upload_file = _parallel_upload_file.__get__(_client)
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


async def upload_to_admin_chat(
    file_path: str,
    chat_id: int,
    status_msg_id: int,
    original_reply_to_message_id: int,
    progress_callback=None,
    width: int = 0,
    height: int = 0,
    duration: int = 0,
) -> Optional[int]:
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
        width/height/duration: video attributes (from bot.video.get_video_metadata).
            Without these, Telethon falls back to its own (hachoir-based) auto-detection,
            which can pick the wrong aspect ratio and never produces a thumbnail - the
            bot.copy_message() forward downstream just inherits whatever attributes this
            upload ends up with, so this is the only place they can be set correctly.

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

        attributes = None
        thumb_path = None
        if width and height:
            attributes = [tl_types.DocumentAttributeVideo(
                duration=duration or 0, w=width, h=height, supports_streaming=True,
            )]
            from .video import generate_thumbnail
            thumb_path = generate_thumbnail(file_path, duration)

        # Upload file (type doesn't matter for caption, use generic send_file)
        try:
            message = await client.send_file(
                admin_entity,
                file_path,
                caption=caption,
                attributes=attributes,
                thumb=thumb_path,
                supports_streaming=True if attributes else False,
                progress_callback=progress_callback or upload_progress_callback
            )
        finally:
            if thumb_path and os.path.exists(thumb_path):
                with suppress(Exception):
                    os.unlink(thumb_path)

        logger.info(f"✅ File uploaded to admin chat: message_id={message.id}, caption={caption}")
        return message.id

    except UploadCancelledError:
        raise
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
