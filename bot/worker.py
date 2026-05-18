# bot/worker.py
import asyncio
import shutil
import tempfile

from telegram import InputMediaPhoto, InputMediaVideo

from bot.utils import get_file_size_mb

from .video import compress_video, get_video_metadata
from .downloaders import download_media
from .config import queue, logger

async def worker():
    while True:
        update, context, url, status_msg, original_reply_to_message_id = await queue.get()

        try:
            message = update.message
            platform = "Instagram" if "instagram.com" in url else "Facebook"

            try:
                await status_msg.edit_text("🤖 I'm on it boss...")
            except:
                pass

            temp_dir = tempfile.mkdtemp()

            try:
                files = await download_media(url, temp_dir)

                if not files:
                    logger.warning(f"No media found in url: {url}")
                    try:
                        await status_msg.edit_text(f"❌ Sorry. Could not fetch from {platform}.")
                    except:
                        pass
                    continue

                if len(files) == 1:
                    file_path = files[0]
                    if file_path.lower().endswith(".mp4"):
                        try:
                            await status_msg.edit_text(f"⚡ Processing ...")
                        except:
                            pass

                        file_path = compress_video(file_path)
                        width, height, duration = get_video_metadata(file_path)
                        try:
                            await status_msg.edit_text(f"🚀 Uploading ...")
                        except:
                            pass
                        await message.reply_video(
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
                    else:
                        await message.reply_photo(
                            photo=open(file_path, "rb"),
                            reply_to_message_id=original_reply_to_message_id,
                        )
                else:
                    media_group = []
                    for f in files[:10]:
                        if f.lower().endswith(".mp4"):
                            f = compress_video(f)
                            media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            media_group.append(InputMediaPhoto(open(f, "rb")))

                    await message.reply_media_group(
                        media=media_group,
                        reply_to_message_id=original_reply_to_message_id,
                    )

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
