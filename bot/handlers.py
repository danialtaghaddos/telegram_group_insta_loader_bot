# bot/handlers.py
import time
import uuid
from contextlib import suppress
from typing import Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from .utils import extract_social_urls
from .config import queue, logger, active_tasks, get_next_task_id

# Quality-picker state for the private-chat flow. Keyed by a short random
# request id embedded in callback_data (e.g. "q:<rid>:tier:high").
PENDING_QUALITY: dict[str, dict] = {}
PENDING_QUALITY_TTL_SECONDS = 600

VIDEO_HEIGHT_BY_TIER = {"high": 720, "medium": 480, "low": 360}
AUDIO_BITRATE_BY_TIER = {"high": "192", "medium": "128", "low": "64"}


def _platform_of(url: str) -> str:
    lower = url.lower()
    if "youtube.com" in lower or "m.youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if "instagram.com" in lower:
        return "instagram"
    if "facebook.com" in lower or "fb.watch" in lower or "fb.com" in lower:
        return "facebook"
    if "x.com" in lower or "twitter.com" in lower:
        return "twitter"
    return "unknown"


def _is_private_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


async def handle_message(urls: list[Any], update: Update, context: ContextTypes.DEFAULT_TYPE, reply_to_message_id: int = None):
    """Handle incoming messages with social media URLs."""
    is_private = _is_private_chat(update)

    for url in urls:
        reply_id = reply_to_message_id or update.message.message_id

        if is_private:
            await _prompt_quality(url, update, context, reply_id)
        else:
            await _queue_download(urls, url, update, context, reply_id, quality=None)


async def _queue_download(urls: list[Any], url: str, update: Update, context: ContextTypes.DEFAULT_TYPE, reply_id: int, quality: Optional[dict]):
    """Create the cancel-able status message and enqueue the download task."""
    status_text = "🤖 I'm on it boss..." if len(urls) == 1 else f"🔜 Items ahead:{len(urls)} — Will get to work soon..."

    task_id = get_next_task_id()
    cancel_keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]
    cancel_markup = InlineKeyboardMarkup(cancel_keyboard)

    status_msg = await update.message.reply_text(
        status_text,
        reply_to_message_id=reply_id,
        reply_markup=cancel_markup
    )

    active_tasks[task_id] = {
        "cancelled": False,
        "temp_dir": None,
        "status_msg": status_msg,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
        "url": url
    }

    await queue.put((update, context, url, status_msg, reply_id, update.message, task_id, quality))


def _prune_pending_quality() -> None:
    now = time.monotonic()
    stale = [rid for rid, req in PENDING_QUALITY.items() if now - req["created"] > PENDING_QUALITY_TTL_SECONDS]
    for rid in stale:
        PENDING_QUALITY.pop(rid, None)


def _tier_keyboard(rid: str) -> list:
    return [[
        InlineKeyboardButton("🔼 High", callback_data=f"q:{rid}:tier:high"),
        InlineKeyboardButton("◻️ Medium", callback_data=f"q:{rid}:tier:medium"),
        InlineKeyboardButton("🔽 Low", callback_data=f"q:{rid}:tier:low"),
    ]]


def _audio_format_keyboard(rid: str) -> list:
    return [[
        InlineKeyboardButton("M4A", callback_data=f"q:{rid}:fmt:m4a"),
        InlineKeyboardButton("MP3", callback_data=f"q:{rid}:fmt:mp3"),
    ]]


async def _prompt_quality(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE, reply_id: int):
    """Show an inline quality/resolution picker before queuing a private-chat download."""
    _prune_pending_quality()

    platform = _platform_of(url)

    # Platforms we don't otherwise recognize shouldn't reach here (extract_social_urls
    # already filters them out), but fall back to the plain flow just in case.
    if platform == "unknown":
        await _queue_download([url], url, update, context, reply_id, quality=None)
        return

    rid = uuid.uuid4().hex[:8]
    PENDING_QUALITY[rid] = {
        "url": url,
        "update": update,
        "context": context,
        "reply_id": reply_id,
        "created": time.monotonic(),
    }

    if platform == "youtube":
        keyboard = [[
            InlineKeyboardButton("🎬 Video", callback_data=f"q:{rid}:kind:video"),
            InlineKeyboardButton("🎵 Audio", callback_data=f"q:{rid}:kind:audio"),
        ]]
        text = "What would you like to download?"
    else:
        keyboard = _tier_keyboard(rid)
        text = "Choose a quality (lower = smaller file size):"

    await update.message.reply_text(text, reply_to_message_id=reply_id, reply_markup=InlineKeyboardMarkup(keyboard))


def _build_quality_dict(pending: dict) -> dict:
    kind = pending.get("kind", "video")
    tier = pending.get("tier", "high")

    if kind == "audio":
        return {
            "kind": "audio",
            "tier": tier,
            "audio_format": pending.get("audio_format", "m4a"),
            "audio_bitrate": AUDIO_BITRATE_BY_TIER[tier],
        }

    return {
        "kind": "video",
        "tier": tier,
        "height_cap": VIDEO_HEIGHT_BY_TIER[tier],
    }


async def handle_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline-keyboard steps of the private-chat quality picker."""
    query = update.callback_query
    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 4:
        return
    _, rid, step, value = parts

    pending = PENDING_QUALITY.get(rid)
    if not pending:
        with suppress(Exception):
            await query.message.edit_text("⌛ This selection has expired. Please resend the link.")
        return

    if step == "kind":
        pending["kind"] = value
        if value == "audio":
            with suppress(Exception):
                await query.message.edit_text("Choose audio format:", reply_markup=InlineKeyboardMarkup(_audio_format_keyboard(rid)))
        else:
            with suppress(Exception):
                await query.message.edit_text("Choose video quality:", reply_markup=InlineKeyboardMarkup(_tier_keyboard(rid)))
        return

    if step == "fmt":
        pending["audio_format"] = value
        with suppress(Exception):
            await query.message.edit_text("Choose audio quality:", reply_markup=InlineKeyboardMarkup(_tier_keyboard(rid)))
        return

    if step == "tier":
        pending["tier"] = value
        PENDING_QUALITY.pop(rid, None)
        quality = _build_quality_dict(pending)

        with suppress(Exception):
            await query.message.delete()

        await _queue_download(
            [pending["url"]],
            pending["url"],
            pending["update"],
            pending["context"],
            pending["reply_id"],
            quality,
        )
        return


async def handle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel button callback for active downloads"""
    query = update.callback_query
    await query.answer("Cancelling...")

    data = query.data
    # Parse task_id from callback data "cancel_{task_id}"
    parts = data.split("_", 1)
    if len(parts) < 2:
        return

    try:
        task_id = int(parts[1])
    except ValueError:
        return

    # Check if task exists
    if task_id not in active_tasks:
        with suppress(Exception):
            await query.message.delete()
        return

    task_info = active_tasks[task_id]

    # Mark as cancelled
    task_info["cancelled"] = True

    # Clean up temp directory if it exists
    if task_info.get("temp_dir"):
        try:
            import shutil
            shutil.rmtree(task_info["temp_dir"], ignore_errors=True)
            logger.info(f"Cleaned up temp directory {task_info['temp_dir']} for cancelled task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to clean up temp directory for task {task_id}: {e}")

    # Update status message
    try:
        await query.message.edit_text("❌ Download cancelled.")
    except Exception as e:
        logger.warning(f"Failed to edit status message for cancellation: {e}")
        with suppress(Exception):
            await query.message.delete()

    # Remove from active_tasks after a short delay to allow the worker to see the cancellation
    # The worker will remove it from active_tasks when it processes the cancellation
    logger.info(f"Task {task_id} marked as cancelled")
