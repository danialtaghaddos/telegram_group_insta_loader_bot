# bot/worker.py
import asyncio
import shutil
import tempfile
import time
from contextlib import suppress

from telegram import InputMediaPhoto, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils import get_file_size_mb, compress_audio

from .video import compress_video, get_video_metadata
from .downloaders import download_media, fetch_instagram_caption
from .config import queue, logger, active_tasks, large_file_captions, ADMIN_USER_ID, UploadCancelledError
from .telethon_client import upload_to_admin_chat


def is_audio_file(file_path: str) -> bool:
    """Check if the file is an audio file"""
    audio_extensions = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus")
    return file_path.lower().endswith(audio_extensions)


def get_audio_duration(file_path: str) -> int:
    """Get audio file duration using ffprobe"""
    try:
        import subprocess
        import json

        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "a:0", "-show_entries",
            "stream=duration", "-show_entries", "format=duration",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        data = json.loads(result.stdout)

        # Try stream duration first, then format duration
        streams = data.get("streams", [])
        if streams and streams[0].get("duration"):
            return int(float(streams[0]["duration"]))

        fmt = data.get("format", {})
        if fmt and fmt.get("duration"):
            return int(float(fmt["duration"]))

        return 0
    except Exception as e:
        logger.warning(f"Failed to get audio duration for {file_path}: {e}")
        return 0


def check_cancelled(task_id: int) -> bool:
    """Check if a task has been cancelled"""
    if task_id not in active_tasks:
        return False
    return active_tasks[task_id].get("cancelled", False)


def cleanup_task(task_id: int):
    """Clean up task resources"""
    if task_id in active_tasks:
        task_info = active_tasks[task_id]
        # Clean up temp directory if it exists
        if task_info.get("temp_dir"):
            try:
                shutil.rmtree(task_info["temp_dir"], ignore_errors=True)
                logger.info(f"Cleaned up temp directory {task_info['temp_dir']} for task {task_id}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory for task {task_id}: {e}")
        # Remove from active tasks
        del active_tasks[task_id]


def _cancel_markup(task_id) -> InlineKeyboardMarkup | None:
    if not task_id:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])


def _make_progress_callback(status_msg, task_id=None, label: str = "Uploading large file"):
    """Build a Telethon-compatible (sync or async) progress callback that
    periodically edits the status message with a percentage, throttled so we
    don't hammer the Bot API with edits. Also polls active_tasks for
    cancellation, aborting the upload by raising UploadCancelledError so a
    click on the Cancel button actually stops the in-flight transfer."""
    state = {"last_percent": -10, "last_time": 0.0}
    markup = _cancel_markup(task_id)

    async def _cb(current, total):
        if check_cancelled(task_id):
            raise UploadCancelledError()
        if not total:
            return
        percent = int(current * 100 / total)
        now = time.monotonic()
        if percent < 100 and (percent - state["last_percent"] < 5 or now - state["last_time"] < 2):
            return
        state["last_percent"] = percent
        state["last_time"] = now
        with suppress(Exception):
            await status_msg.edit_text(
                f"🚀 {label}... {percent}%\n🔜 This may take a few minutes",
                reply_markup=markup,
            )

    return _cb


async def worker():
    while True:
        result = await queue.get()
        # Support old 6/7-tuple formats (no quality dict) as well as the current 8-tuple.
        if len(result) == 8:
            update, context, url, status_msg, original_reply_to_message_id, message, task_id, quality = result
        elif len(result) == 7:
            update, context, url, status_msg, original_reply_to_message_id, message, task_id = result
            quality = None
        elif len(result) == 6:
            update, context, url, status_msg, original_reply_to_message_id, message = result
            task_id = None
            quality = None
        else:
            update, context, url, status_msg, original_reply_to_message_id = result
            message = update.message
            task_id = None
            quality = None

        quality = quality or {}

        try:
            # Fallback: try to get message from update, then from status_msg.reply_to_message
            if message is None:
                message = update.effective_message if update.effective_message else None
            if message is None and status_msg and status_msg.reply_to_message:
                message = status_msg.reply_to_message

            # Get chat_id for fallback sending (when message is None)
            chat_id = status_msg.chat_id if status_msg else None
            if chat_id is None:
                chat_id = update.effective_chat.id if update.effective_chat else None

            is_private = bool(update.effective_chat and update.effective_chat.type == "private")
            video_tier = quality.get("tier") if quality else None
            cancel_markup = _cancel_markup(task_id)

            url_lower = url.lower()
            if "youtube.com" in url_lower or "m.youtube.com" in url_lower or "youtu.be" in url_lower:
                platform = "YouTube"
            elif "instagram.com" in url_lower:
                platform = "Instagram"
            elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
                platform = "Facebook"
            elif "x.com" in url_lower or "twitter.com" in url_lower:
                platform = "Twitter/X"
            else:
                platform = "Unknown"

            with suppress(Exception):
                await status_msg.edit_text("🤖 Loading...")

            temp_dir = tempfile.mkdtemp()

            # Store temp_dir in active_tasks for cleanup on cancellation
            if task_id and task_id in active_tasks:
                active_tasks[task_id]["temp_dir"] = temp_dir

            try:
                # Check if cancelled before starting download
                if check_cancelled(task_id):
                    logger.info(f"Task {task_id} cancelled before download")
                    with suppress(Exception):
                        await status_msg.delete()
                    continue

                # Download media
                files = await download_media(url, temp_dir, quality)

                # Check if cancelled after download
                if check_cancelled(task_id):
                    logger.info(f"Task {task_id} cancelled after download")
                    with suppress(Exception):
                        await status_msg.delete()
                    continue

                if not files:
                    logger.warning(f"No media found in url: {url}")
                    with suppress(Exception):
                        await status_msg.edit_text(f"❌ Sorry. Could not fetch from {platform}.")
                    continue

                # Fetch Instagram caption if available
                caption = ""
                if "instagram.com" in url:
                    # Check if cancelled before fetching caption
                    if check_cancelled(task_id):
                        logger.info(f"Task {task_id} cancelled before caption fetch")
                        with suppress(Exception):
                            await status_msg.delete()
                        continue

                    with suppress(Exception):
                        await status_msg.edit_text(f"📝 Fetching caption...")
                    caption = await fetch_instagram_caption(url)

                # Private chats: send the full caption as a separate follow-up message
                # (avoids Telegram's 1024-char caption limit). Groups: keep the
                # existing behavior of attaching a truncated caption to the media.
                caption_attach = None
                caption_followup = None
                if caption:
                    if is_private:
                        caption_followup = caption if len(caption) <= 4096 else caption[:4093] + "..."
                    else:
                        caption_attach = caption if len(caption) <= 1000 else caption[:997] + "..."

                uploaded_chat_id = None
                uploaded_message_ids = None

                if len(files) == 1:
                    file_path = files[0]
                    if is_audio_file(file_path):
                        # Handle audio files (MP3, M4A, etc.)
                        # Check if cancelled before processing
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before audio processing")
                            with suppress(Exception):
                                await status_msg.delete()
                            continue

                        with suppress(Exception):
                            await status_msg.edit_text(f"⚡ Processing audio ...")

                        # Check file size
                        file_size_mb = get_file_size_mb(file_path)
                        logger.info(f"Audio file size: {file_size_mb:.1f}MB")

                        if file_size_mb > 50:
                            # File is too large for Telegram bot, use Telethon user account
                            logger.info(f"Audio file {file_size_mb:.1f}MB exceeds 50MB limit, using Telethon")

                            with suppress(Exception):
                                await status_msg.edit_text(
                                    f"🚀 Uploading large file ...\n🔜 This may take a few minutes",
                                    reply_markup=cancel_markup,
                                )

                            progress_cb = _make_progress_callback(status_msg, task_id)

                            # Upload to admin chat using Telethon
                            # Caption format: chat_id-status_msg_id-file_name
                            try:
                                admin_msg_id = await upload_to_admin_chat(
                                    file_path, chat_id, status_msg.message_id,
                                    update.effective_message.message_id if update.effective_message else original_reply_to_message_id,
                                    progress_callback=progress_cb,
                                )
                            except UploadCancelledError:
                                logger.info(f"Task {task_id} cancelled during large audio upload")
                                with suppress(Exception):
                                    await status_msg.edit_text("❌ Download cancelled.")
                                continue

                            if admin_msg_id:
                                logger.info(f"✅ Large file uploaded to admin chat. Admin should forward to bot.")
                                # The bot will handle the file when admin forwards it
                                # Just delete the status message - the bot will send the file as its own
                                with suppress(Exception):
                                    await status_msg.delete()
                            else:
                                logger.error("Telethon upload failed")
                                with suppress(Exception):
                                    await status_msg.edit_text(
                                        "❌ File too large for bot. Please set up Telethon session.\n"
                                        "Run: python generate_session.py"
                                    )
                            continue

                        # File is within limit, upload normally via bot
                        with suppress(Exception):
                            await status_msg.edit_text(f"🚀 Uploading audio ...")

                        # Get audio duration using ffprobe
                        duration = get_audio_duration(file_path)

                        if message:
                            sent_msg = await message.reply_audio(
                                audio=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                duration=duration,
                                read_timeout=300,
                                write_timeout=300,
                                connect_timeout=60,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                        elif chat_id:
                            sent_msg = await context.bot.send_audio(
                                chat_id=chat_id,
                                audio=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                duration=duration,
                                read_timeout=300,
                                write_timeout=300,
                                connect_timeout=60,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                    elif file_path.lower().endswith(".mp4"):
                        # Skip compression if file is from cache (already compressed)
                        original_file_path = file_path
                        with suppress(Exception):
                            await status_msg.edit_text(f"⚡ Processing ...")

                        # Check if cancelled before compression
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before video compression")
                            with suppress(Exception):
                                await status_msg.edit_text("❌ Download cancelled.")
                            continue

                        file_path = compress_video(file_path, tier=video_tier)
                        # Update files list if compression created a new file
                        if file_path != original_file_path and len(files) == 1:
                            files = [file_path]
                        width, height, duration = get_video_metadata(file_path)

                        # Check if cancelled before upload
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before video upload")
                            with suppress(Exception):
                                await status_msg.edit_text("❌ Download cancelled.")
                            continue

                        file_size_mb = get_file_size_mb(file_path)

                        if is_private and file_size_mb > 50:
                            # Too large for the bot to upload directly; forward via the
                            # admin's Telethon account, with live progress updates.
                            logger.info(f"Video file {file_size_mb:.1f}MB exceeds 50MB limit, using Telethon")

                            if caption_followup:
                                large_file_captions[f"{chat_id}:{status_msg.message_id}"] = caption_followup

                            with suppress(Exception):
                                await status_msg.edit_text(
                                    "🚀 Uploading large file ...\n🔜 This may take a few minutes",
                                    reply_markup=cancel_markup,
                                )

                            progress_cb = _make_progress_callback(status_msg, task_id)
                            try:
                                admin_msg_id = await upload_to_admin_chat(
                                    file_path, chat_id, status_msg.message_id,
                                    update.effective_message.message_id if update.effective_message else original_reply_to_message_id,
                                    progress_callback=progress_cb,
                                    width=width, height=height, duration=duration,
                                )
                            except UploadCancelledError:
                                logger.info(f"Task {task_id} cancelled during large video upload")
                                large_file_captions.pop(f"{chat_id}:{status_msg.message_id}", None)
                                with suppress(Exception):
                                    await status_msg.edit_text("❌ Download cancelled.")
                                continue

                            if admin_msg_id:
                                logger.info("✅ Large video uploaded to admin chat. Admin should forward to bot.")
                                with suppress(Exception):
                                    await status_msg.delete()
                            else:
                                logger.error("Telethon upload failed")
                                large_file_captions.pop(f"{chat_id}:{status_msg.message_id}", None)
                                with suppress(Exception):
                                    await status_msg.edit_text(
                                        "❌ File too large for bot. Please set up Telethon session.\n"
                                        "Run: python generate_session.py"
                                    )
                            continue

                        with suppress(Exception):
                            await status_msg.edit_text(f"🚀 Uploading ...")
                        if message:
                            sent_msg = await message.reply_video(
                                video=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                supports_streaming=True,
                                width=width,
                                height=height,
                                duration=duration,
                                caption=caption_attach,
                                read_timeout=300,
                                write_timeout=300,
                                connect_timeout=60,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                        elif chat_id:
                            sent_msg = await context.bot.send_video(
                                chat_id=chat_id,
                                video=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                supports_streaming=True,
                                width=width,
                                height=height,
                                duration=duration,
                                caption=caption_attach,
                                read_timeout=300,
                                write_timeout=300,
                                connect_timeout=60,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                    else:
                        # Check if cancelled before uploading photo
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before photo upload")
                            with suppress(Exception):
                                await status_msg.edit_text("❌ Download cancelled.")
                            continue

                        if message:
                            sent_msg = await message.reply_photo(
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                caption=caption_attach,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                        elif chat_id:
                            sent_msg = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                caption=caption_attach,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                else:
                    media_group = []
                    # Track updated file paths for caching
                    updated_files = []
                    for i, f in enumerate(files[:10]):
                        # Check if cancelled during media group processing
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled during media group processing")
                            with suppress(Exception):
                                await status_msg.edit_text("❌ Download cancelled.")
                            break

                        if is_audio_file(f):
                            # Note: Telegram doesn't support audio in media groups
                            # Send audio files separately
                            updated_files.append(f)
                            pass
                        elif f.lower().endswith(".mp4"):
                            original_f = f
                            f = compress_video(f, tier=video_tier)
                            # Track the updated file path
                            if f != original_f:
                                files[i] = f
                            updated_files.append(f)
                            # Add caption to the first item in media group (groups only)
                            if i == 0 and caption_attach:
                                media_group.append(InputMediaVideo(open(f, "rb"), caption=caption_attach))
                            else:
                                media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            updated_files.append(f)
                            # Add caption to the first item in media group (groups only)
                            if i == 0 and caption_attach:
                                media_group.append(InputMediaPhoto(open(f, "rb"), caption=caption_attach))
                            else:
                                media_group.append(InputMediaPhoto(open(f, "rb")))
                    files = updated_files

                    # Check if cancelled before sending media group
                    if not check_cancelled(task_id):
                        if message:
                            sent_msgs = await message.reply_media_group(
                                media=media_group,
                                reply_to_message_id=original_reply_to_message_id,
                            )
                            if sent_msgs:
                                uploaded_chat_id = sent_msgs[0].chat_id
                                uploaded_message_ids = [m.message_id for m in sent_msgs]
                        elif chat_id:
                            sent_msgs = await context.bot.send_media_group(
                                chat_id=chat_id,
                                media=media_group,
                                reply_to_message_id=original_reply_to_message_id,
                            )
                            if sent_msgs:
                                uploaded_chat_id = sent_msgs[0].chat_id
                                uploaded_message_ids = [m.message_id for m in sent_msgs]

                # Private chats: deliver the full caption as its own message, replying
                # to the media we just sent.
                if caption_followup and uploaded_chat_id and uploaded_message_ids:
                    with suppress(Exception):
                        await context.bot.send_message(
                            chat_id=uploaded_chat_id,
                            text=caption_followup,
                            reply_to_message_id=uploaded_message_ids[0],
                        )

                # No caching: skip updating any cache metadata

                with suppress(Exception):
                    await status_msg.delete()

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker error for {url}: {e}")
            with suppress(Exception):
                await status_msg.edit_text("❌ Link appears to be broken, or I'm broken.")

        finally:
            # Clean up task from active_tasks
            if task_id:
                cleanup_task(task_id)

            await asyncio.sleep(30)
            queue.task_done()
