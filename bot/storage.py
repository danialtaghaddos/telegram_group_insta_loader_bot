"""
Telegram Saved Messages storage module for persistent data storage.

On startup, syncs all data files from Telegram Saved Messages to local files.
On write, persists to local files immediately and uploads to Telegram asynchronously.
Falls back to local files when Telegram is unavailable.
"""

import asyncio
import io
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from .config import logger

LOCAL_STORAGE_ROOT = Path(
    os.getenv("BOT_STORAGE_DIR")
    or ("/data" if Path("/data").exists() else Path(__file__).resolve().parent.parent / "data")
)

_COOKIE_FILE_NAMES = [
    "instagram_cookies.txt",
    "facebook_cookies.txt",
    "youtube_cookies.txt",
    "twitter_cookies.txt",
]


class TelegramSavedMessagesStorage:
    """Storage backend using Telegram Saved Messages with local file fallback."""

    def __init__(self, file_name: str, default_value: Any):
        self.file_name = file_name  # without .json extension
        self.default_value = default_value
        self._lock = threading.Lock()
        self._message_id: Optional[int] = None

    def _local_path(self) -> Path:
        return LOCAL_STORAGE_ROOT / f"{self.file_name}.json"

    def _read_local(self) -> Any:
        path = self._local_path()
        if not path.exists():
            return self.default_value
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Local read failed for '{self.file_name}': {exc}")
            return self.default_value

    def _write_local(self, data: Any) -> bool:
        try:
            self._local_path().parent.mkdir(parents=True, exist_ok=True)
            with self._local_path().open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            return True
        except OSError as exc:
            logger.warning(f"Local write failed for '{self.file_name}': {exc}")
            return False

    def read(self) -> Any:
        return self._read_local()

    def write(self, data: Any) -> bool:
        result = self._write_local(data)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._upload_to_telegram(data))
        except RuntimeError:
            pass  # No running loop at module-init time
        return result

    async def _upload_to_telegram(self, data: Any) -> None:
        from .telethon_client import get_telethon_client
        client = get_telethon_client()
        if not client:
            return
        try:
            if not client.is_connected():
                await client.connect()
            from telethon.tl.types import DocumentAttributeFilename
            caption = f"{self.file_name}.json"
            content = json.dumps(data, ensure_ascii=True, indent=2).encode("utf-8")
            message = await client.send_file(
                "me",
                io.BytesIO(content),
                caption=caption,
                attributes=[DocumentAttributeFilename(caption)],
                force_document=True,
            )
            old_id = self._message_id
            self._message_id = message.id
            if old_id and old_id != message.id:
                try:
                    await client.delete_messages("me", [old_id])
                except Exception:
                    pass
            logger.debug(f"Uploaded '{caption}' to Saved Messages (msg_id={message.id})")
        except Exception as exc:
            logger.warning(f"Failed to upload '{self.file_name}' to Telegram: {exc}")

    async def fetch_from_telegram(self) -> Optional[Any]:
        """Download the latest version from Saved Messages and update local cache."""
        from .telethon_client import get_telethon_client
        client = get_telethon_client()
        if not client:
            return None
        try:
            if not client.is_connected():
                await client.connect()
            search_term = f"{self.file_name}.json"
            async for message in client.iter_messages("me", search=search_term):
                if not message.document:
                    continue
                raw = await client.download_media(message, bytes)
                data = json.loads(raw.decode("utf-8"))
                self._message_id = message.id
                self._write_local(data)
                logger.info(f"Synced '{search_term}' from Saved Messages")
                return data
        except Exception as exc:
            logger.warning(f"Failed to fetch '{self.file_name}' from Telegram: {exc}")
        return None


# ── Storage instances ──────────────────────────────────────────────────────────

_activated_chats_storage: Optional[TelegramSavedMessagesStorage] = None
_doorman_chats_storage: Optional[TelegramSavedMessagesStorage] = None
_moderators_storage: Optional[TelegramSavedMessagesStorage] = None
_access_requests_storage: Optional[TelegramSavedMessagesStorage] = None


def _get_activated_chats_storage() -> TelegramSavedMessagesStorage:
    global _activated_chats_storage
    if _activated_chats_storage is None:
        _activated_chats_storage = TelegramSavedMessagesStorage("activated_chats", [])
    return _activated_chats_storage


def _get_doorman_chats_storage() -> TelegramSavedMessagesStorage:
    global _doorman_chats_storage
    if _doorman_chats_storage is None:
        _doorman_chats_storage = TelegramSavedMessagesStorage("doorman_chats", [])
    return _doorman_chats_storage


def _get_moderators_storage() -> TelegramSavedMessagesStorage:
    global _moderators_storage
    if _moderators_storage is None:
        _moderators_storage = TelegramSavedMessagesStorage("moderators", {"moderators": {}})
    return _moderators_storage


def _get_access_requests_storage() -> TelegramSavedMessagesStorage:
    global _access_requests_storage
    if _access_requests_storage is None:
        _access_requests_storage = TelegramSavedMessagesStorage("access_requests", [])
    return _access_requests_storage


# ── Public load / save functions ───────────────────────────────────────────────

def load_activated_chats() -> set[int]:
    data = _get_activated_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_activated_chats(chats: set[int]) -> None:
    storage = _get_activated_chats_storage()
    success = storage.write(list(chats))
    logger.debug("Saved activated chats (success: %s)", success)


def load_doorman_chats() -> set[int]:
    data = _get_doorman_chats_storage().read()
    return set(data) if isinstance(data, list) else set()


def save_doorman_chats(chats: set[int]) -> None:
    storage = _get_doorman_chats_storage()
    success = storage.write(list(chats))
    logger.debug("Saved doorman chats (success: %s)", success)


def load_moderators_from_storage() -> dict[int, list[int]]:
    data = _get_moderators_storage().read()
    if isinstance(data, dict):
        if "moderators" in data:
            moderators_data = data["moderators"]
            if isinstance(moderators_data, dict):
                return {int(k): v for k, v in moderators_data.items()}
        elif data:
            return {int(k): v for k, v in data.items()}
    return {}


def save_moderators_to_storage(moderators_data: dict[int, set[int]]) -> None:
    data = {"moderators": {str(k): list(v) for k, v in moderators_data.items()}}
    _get_moderators_storage().write(data)


def load_access_requests_from_storage() -> list[dict]:
    data = _get_access_requests_storage().read()
    return data if isinstance(data, list) else []


def save_access_requests_to_storage(requests_data: list[dict]) -> None:
    _get_access_requests_storage().write(requests_data)


# ── Startup sync from Telegram ─────────────────────────────────────────────────

async def initialize_from_telegram() -> None:
    """Sync all storage and cookie files from Telegram Saved Messages to local files.

    Called once at bot startup before loading in-memory state. After this returns,
    local files hold the authoritative data and all subsequent reads use them.
    """
    storages = [
        _get_activated_chats_storage(),
        _get_doorman_chats_storage(),
        _get_moderators_storage(),
        _get_access_requests_storage(),
    ]
    for storage in storages:
        await storage.fetch_from_telegram()

    for cookie_name in _COOKIE_FILE_NAMES:
        await _fetch_cookie_from_telegram(cookie_name)


# ── Cookie storage ─────────────────────────────────────────────────────────────

def _cookie_local_path(file_name: str) -> Path:
    return LOCAL_STORAGE_ROOT / file_name


async def _fetch_cookie_from_telegram(file_name: str) -> None:
    """Download a cookie file from Saved Messages to local storage."""
    from .telethon_client import get_telethon_client
    client = get_telethon_client()
    if not client:
        return
    try:
        if not client.is_connected():
            await client.connect()
        async for message in client.iter_messages("me", search=file_name):
            if not message.document:
                continue
            raw = await client.download_media(message, bytes)
            dest = _cookie_local_path(file_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            logger.info(f"Synced '{file_name}' from Saved Messages")
            return
    except Exception as exc:
        logger.warning(f"Failed to fetch '{file_name}' from Telegram: {exc}")


def _load_cookie_local(file_name: str) -> str:
    path = _cookie_local_path(file_name)
    if path.exists() and path.stat().st_size > 10:
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to read local cookie '{file_name}': {exc}")
    return ""


def load_instagram_cookies() -> str:
    return _load_cookie_local("instagram_cookies.txt")


def load_facebook_cookies() -> str:
    return _load_cookie_local("facebook_cookies.txt")


def load_youtube_cookies() -> str:
    return _load_cookie_local("youtube_cookies.txt")


def load_twitter_cookies() -> str:
    return _load_cookie_local("twitter_cookies.txt")
