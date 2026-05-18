# bot/worker.py
import asyncio
import shutil
import tempfile

from telegram import InputMediaPhoto, InputMediaVideo

from bot.utils import get_file_size_mb

from .video import compress_video, get_video_metadata
from .downloaders import download_media
from .config import queue, logger, CACHE_ENABLE_FORWARDING
from .file_cache import get_cache_metadata, add_cache_entry, is_cache_valid


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

async def worker():
    while True:
        result = await queue.get()
        # Support both old 5-tuple and new 6-tuple format
        if len(result) == 6:
            update, context, url, status_msg, original_reply_to_message_id, message = result
        else:
            update, context, url, status_msg, original_reply_to_message_id = result
            message = update.message

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
            if "youtube.com" in url or "youtu.be" in url:
                platform = "YouTube"
            elif "instagram.com" in url:
                platform = "Instagram"
            elif "facebook.com" in url or "fb.watch" in url or "fb.com" in url:
                platform = "Facebook"
            else:
                platform = "Unknown"

            try:
                await status_msg.edit_text("🤖 I'm on it boss...")
            except:
                pass

            temp_dir = tempfile.mkdtemp()

            try:
                # Check if we can forward a previous upload instead of downloading
                if CACHE_ENABLE_FORWARDING:
                    meta = get_cache_metadata(url)
                    if meta and 'last_upload' in meta:
                        last_upload = meta['last_upload']
                        chat_id_from_meta = last_upload.get('chat_id')
                        message_ids = last_upload.get('message_ids', [])
                        if chat_id_from_meta and message_ids:
                            try:
                                # Determine target chat_id
                                target_chat_id = None
                                if message:
                                    target_chat_id = message.chat_id
                                elif status_msg:
                                    target_chat_id = status_msg.chat_id
                                else:
                                    target_chat_id = update.effective_chat.id if update.effective_chat else None
                                if target_chat_id:
                                    # Determine the message ID to reply to (the original request)
                                    reply_to_id = original_reply_to_message_id
                                    if reply_to_id is None and message:
                                        reply_to_id = message.message_id
                                    
                                    # Forward each message with a reply indicator
                                    forwarded = []
                                    for msg_id in message_ids:
                                        try:
                                            # Then forward the cached message (reply to the emoji message)
                                            fwd = await context.bot.forward_message(
                                                chat_id=target_chat_id,
                                                from_chat_id=chat_id_from_meta,
                                                message_id=msg_id
                                            )
                                            # First send a reply with 👇 emoji to the original message
                                            emoji_msg = await context.bot.send_message(
                                                chat_id=target_chat_id,
                                                text="👆 👆 👆",
                                                reply_to_message_id=reply_to_id
                                            )
                                            forwarded.append(fwd)
                                        except Exception as e:
                                            logger.warning(f"Failed to forward message {msg_id} from {chat_id_from_meta}: {e}")
                                    if forwarded:
                                        logger.info(f"Forwarded {len(forwarded)} message(s) for {url}")
                                        try:
                                            await status_msg.delete()
                                        except:
                                            pass
                                        continue  # Skip download and upload
                            except Exception as e:
                                logger.warning(f"Forwarding failed for {url}, falling back to download: {e}")

                # Check if we're using cached files (to skip re-compression)
                is_from_cache = is_cache_valid(url)
                files = await download_media(url, temp_dir)

                if not files:
                    logger.warning(f"No media found in url: {url}")
                    try:
                        await status_msg.edit_text(f"❌ Sorry. Could not fetch from {platform}.")
                    except:
                        pass
                    continue

                # Track uploaded message info for caching
                uploaded_chat_id = None
                uploaded_message_ids = []

                if len(files) == 1:
                    file_path = files[0]
                    if is_audio_file(file_path):
                        # Handle audio files (MP3, M4A, etc.)
                        try:
                            await status_msg.edit_text(f"⚡ Processing audio ...")
                        except:
                            pass
                        
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
                        if not is_from_cache:
                            try:
                                await status_msg.edit_text(f"⚡ Processing ...")
                            except:
                                pass
                            file_path = compress_video(file_path)
                        # Update files list if compression created a new file
                        if file_path != original_file_path and len(files) == 1:
                            files = [file_path]
                        width, height, duration = get_video_metadata(file_path)
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
                                read_timeout=300,
                                write_timeout=300,
                                connect_timeout=60,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                    else:
                        if message:
                            sent_msg = await message.reply_photo(
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                        elif chat_id:
                            sent_msg = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=open(file_path, "rb"),
                                reply_to_message_id=original_reply_to_message_id,
                            )
                            uploaded_chat_id = sent_msg.chat_id
                            uploaded_message_ids = [sent_msg.message_id]
                else:
                    media_group = []
                    # Track updated file paths for caching
                    updated_files = []
                    for i, f in enumerate(files[:10]):
                        if is_audio_file(f):
                            # Note: Telegram doesn't support audio in media groups
                            # Send audio files separately
                            updated_files.append(f)
                            pass
                        elif f.lower().endswith(".mp4"):
                            original_f = f
                            # Skip compression if file is from cache (already compressed)
                            if not is_from_cache:
                                f = compress_video(f)
                            # Track the updated file path
                            if f != original_f:
                                files[i] = f
                            updated_files.append(f)
                            media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            updated_files.append(f)
                            media_group.append(InputMediaPhoto(open(f, "rb")))
                    files = updated_files

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

                # Update cache with upload info for future forwarding
                if not is_from_cache and uploaded_chat_id and uploaded_message_ids:
                    add_cache_entry(url, files, last_upload={
                        "chat_id": uploaded_chat_id,
                        "message_ids": uploaded_message_ids
                    })

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
            await asyncio.sleep(30)
            queue.task_done()