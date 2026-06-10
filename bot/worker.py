# bot/worker.py
import asyncio
import shutil
import tempfile

from telegram import InputMediaPhoto, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils import get_file_size_mb, compress_audio

from .video import compress_video, get_video_metadata
from .downloaders import download_media, fetch_instagram_caption
from .config import queue, logger, active_tasks
from .storage import upload_file_to_drive


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


async def worker():
    while True:
        result = await queue.get()
        # Support both old 6-tuple and new 7-tuple format (with task_id)
        if len(result) == 7:
            update, context, url, status_msg, original_reply_to_message_id, message, task_id = result
        elif len(result) == 6:
            update, context, url, status_msg, original_reply_to_message_id, message = result
            task_id = None
        else:
            update, context, url, status_msg, original_reply_to_message_id = result
            message = update.message
            task_id = None

        try:
            # Fallback: try to get message from update, then from status_msg.reply_to_message
            if message is None:
                message = update.message if update.message else None
            if message is None and status_msg and status_msg.reply_to_message:
                message = status_msg.reply_to_message
            
            # Get chat_id for fallback sending (when message is None)
            chat_id = None
            if message is None:
                chat_id = status_msg.chat_id if status_msg else None
                if chat_id is None:
                    chat_id = update.effective_chat.id if update.effective_chat else None
            
            url_lower = url.lower()
            if "youtube.com" in url_lower or "m.youtube.com" in url_lower or "youtu.be" in url_lower:
                platform = "YouTube"
            elif "instagram.com" in url_lower:
                platform = "Instagram"
            elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
                platform = "Facebook"
            else:
                platform = "Unknown"

            try:
                await status_msg.edit_text("🤖 I'm on it boss...")
            except:
                pass

            temp_dir = tempfile.mkdtemp()

            # Store temp_dir in active_tasks for cleanup on cancellation
            if task_id and task_id in active_tasks:
                active_tasks[task_id]["temp_dir"] = temp_dir

            try:
                # Check if cancelled before starting download
                if check_cancelled(task_id):
                    logger.info(f"Task {task_id} cancelled before download")
                    try:
                        await status_msg.edit_text("❌ Download cancelled.")
                    except:
                        pass
                    continue

                # Download media
                files = await download_media(url, temp_dir)

                # Check if cancelled after download
                if check_cancelled(task_id):
                    logger.info(f"Task {task_id} cancelled after download")
                    try:
                        await status_msg.edit_text("❌ Download cancelled.")
                    except:
                        pass
                    continue

                if not files:
                    logger.warning(f"No media found in url: {url}")
                    try:
                        await status_msg.edit_text(f"❌ Sorry. Could not fetch from {platform}.")
                    except:
                        pass
                    continue

                # Fetch Instagram caption if available
                caption = ""
                if "instagram.com" in url:
                    # Check if cancelled before fetching caption
                    if check_cancelled(task_id):
                        logger.info(f"Task {task_id} cancelled before caption fetch")
                        try:
                            await status_msg.edit_text("❌ Download cancelled.")
                        except:
                            pass
                        continue

                    try:
                        await status_msg.edit_text(f"📝 Fetching caption...")
                    except:
                        pass
                    caption = await fetch_instagram_caption(url)
                    # Truncate caption if too long (Telegram limit is 1024 chars)
                    if caption and len(caption) > 1000:
                        caption = caption[:997] + "..."

                # Track uploaded message info for caching
                uploaded_chat_id = None
                uploaded_message_ids = []

                if len(files) == 1:
                    file_path = files[0]
                    if is_audio_file(file_path):
                        # Handle audio files (MP3, M4A, etc.)
                        # Check if cancelled before processing
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before audio processing")
                            try:
                                await status_msg.edit_text("❌ Download cancelled.")
                            except:
                                pass
                            continue

                        try:
                            await status_msg.edit_text(f"⚡ Processing audio ...")
                        except:
                            pass
                        
                        # Check file size - if > 50MB, ask user for choice
                        file_size_mb = get_file_size_mb(file_path)
                        logger.info(f"Audio file size: {file_size_mb:.1f}MB")
                        
                        if file_size_mb > 50:
                            # File is too large for Telegram, ask user for choice
                            logger.info(f"Audio file {file_size_mb:.1f}MB exceeds 50MB limit, asking user for choice")
                            
                            # Store file path in task info for later use
                            if task_id and task_id in active_tasks:
                                active_tasks[task_id]["audio_file_path"] = file_path
                            
                            # Create keyboard with compression and Google Drive options
                            keyboard = [
                                [InlineKeyboardButton("🗜️ Compress & Send", callback_data=f"compress_{task_id}")],
                                [InlineKeyboardButton("📁 Google Drive", callback_data=f"drive_{task_id}")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            try:
                                await status_msg.edit_text(
                                    f"⚠️ Audio file is {file_size_mb:.1f}MB (limit is 50MB).\n\n"
                                    f"Choose an option:",
                                    reply_markup=reply_markup
                                )
                            except:
                                pass
                            
                            # Wait for user to choose (poll for action)
                            user_action = None
                            wait_attempts = 0
                            max_wait_attempts = 120  # Wait up to 60 seconds (2 seconds * 30 attempts)
                            
                            while wait_attempts < max_wait_attempts:
                                if check_cancelled(task_id):
                                    logger.info(f"Task {task_id} cancelled while waiting for user choice")
                                    try:
                                        await status_msg.edit_text("❌ Download cancelled.")
                                    except:
                                        pass
                                    break
                                
                                # Check if user has made a choice
                                task_info = active_tasks.get(task_id, {})
                                user_action = task_info.get("large_file_action")
                                
                                if user_action:
                                    logger.info(f"User chose: {user_action}")
                                    break
                                
                                await asyncio.sleep(0.5)
                                wait_attempts += 1
                            
                            if not user_action or check_cancelled(task_id):
                                continue
                            
                            # Update status based on user choice
                            if user_action == "compress":
                                try:
                                    await status_msg.edit_text("🗜️ Compressing audio...")
                                except:
                                    pass
                                
                                # Compress audio
                                file_path = compress_audio(file_path)
                                file_size_mb = get_file_size_mb(file_path)
                                logger.info(f"Compressed audio size: {file_size_mb:.1f}MB")
                                
                                # If still too large after compression, fall back to Google Drive
                                if file_size_mb > 50:
                                    logger.info(f"Compressed file still {file_size_mb:.1f}MB, using Google Drive")
                                    try:
                                        await status_msg.edit_text("📁 Uploading to Google Drive...")
                                    except:
                                        pass
                                    user_action = "drive"
                            
                            if user_action == "drive":
                                # Upload to Google Drive
                                try:
                                    await status_msg.edit_text("📁 Uploading to Google Drive...")
                                except:
                                    pass
                                
                                drive_link = upload_file_to_drive(file_path)
                                
                                if drive_link:
                                    try:
                                        await status_msg.edit_text(
                                            f"📁 File uploaded to Google Drive ({file_size_mb:.1f}MB):\n\n"
                                            f"{drive_link}\n\n"
                                            f"Click the link to download."
                                        )
                                    except:
                                        if chat_id:
                                            await context.bot.send_message(
                                                chat_id=chat_id,
                                                text=f"📁 File uploaded to Google Drive ({file_size_mb:.1f}MB):\n\n{drive_link}"
                                            )
                                    logger.info(f"✅ Uploaded to Google Drive: {drive_link}")
                                else:
                                    try:
                                        await status_msg.edit_text("❌ Failed to upload to Google Drive.")
                                    except:
                                        pass
                                    logger.error("Google Drive upload failed")
                                continue
                            
                            # If user chose compress and it worked, fall through to upload
                            # Check if cancelled before uploading after compression
                            if check_cancelled(task_id):
                                logger.info(f"Task {task_id} cancelled before audio upload")
                                try:
                                    await status_msg.edit_text("❌ Download cancelled.")
                                except:
                                    pass
                                continue
                        
                        # File is within limit or was compressed successfully
                        try:
                            await status_msg.edit_text(f"🚀 Uploading audio ...")
                        except:
                            pass
                        
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
                        try:
                            await status_msg.edit_text(f"⚡ Processing ...")
                        except:
                            pass
                        
                        # Check if cancelled before compression
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before video compression")
                            try:
                                await status_msg.edit_text("❌ Download cancelled.")
                            except:
                                pass
                            continue

                        file_path = compress_video(file_path)
                        # Update files list if compression created a new file
                        if file_path != original_file_path and len(files) == 1:
                            files = [file_path]
                        width, height, duration = get_video_metadata(file_path)

                        # Check if cancelled before upload
                        if check_cancelled(task_id):
                            logger.info(f"Task {task_id} cancelled before video upload")
                            try:
                                await status_msg.edit_text("❌ Download cancelled.")
                            except:
                                pass
                            continue

                        try:
                            await status_msg.edit_text(f"🚀 Uploading ...")
                        except:
                            pass
                        if message:
                            sent_msg = await message.reply_video(
                                video=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                supports_streaming=True,
                                width=width,
                                height=height,
                                duration=duration,
                                caption=caption if caption else None,
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
                                caption=caption if caption else None,
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
                            try:
                                await status_msg.edit_text("❌ Download cancelled.")
                            except:
                                pass
                            continue

                        if message:
                            sent_msg = await message.reply_photo(
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                caption=caption if caption else None,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                        elif chat_id:
                            sent_msg = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                                caption=caption if caption else None,
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
                            try:
                                await status_msg.edit_text("❌ Download cancelled.")
                            except:
                                pass
                            break

                        if is_audio_file(f):
                            # Note: Telegram doesn't support audio in media groups
                            # Send audio files separately
                            updated_files.append(f)
                            pass
                        elif f.lower().endswith(".mp4"):
                            original_f = f
                            f = compress_video(f)
                            # Track the updated file path
                            if f != original_f:
                                files[i] = f
                            updated_files.append(f)
                            # Add caption to the first item in media group
                            if i == 0 and caption:
                                media_group.append(InputMediaVideo(open(f, "rb"), caption=caption))
                            else:
                                media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            updated_files.append(f)
                            # Add caption to the first item in media group
                            if i == 0 and caption:
                                media_group.append(InputMediaPhoto(open(f, "rb"), caption=caption))
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

                # No caching: skip updating any cache metadata

                try:
                    await status_msg.delete()
                except:
                    pass

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker error for {url}: {e}")
            try:
                await status_msg.edit_text("❌ Link appears to be broken, or I'm broken.")
            except:
                pass

        finally:
            # Clean up task from active_tasks
            if task_id:
                cleanup_task(task_id)
            
            await asyncio.sleep(30)
            queue.task_done()