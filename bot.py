import os
import re
import asyncio
import logging
import tempfile
import shutil
import subprocess

from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

import yt_dlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

MAX_MEDIA_PER_MESSAGE = 5
queue: asyncio.Queue = asyncio.Queue(maxsize=30)


def get_cookies_file():
    path = "/tmp/cookies.txt"
    
    if os.path.exists(path):
        return path
    cookies = os.getenv("COOKIES_TXT")
    if not cookies:
        return None

    with open(path, "w") as f:
        f.write(cookies)

    return path


# ---------- UTIL ----------
def extract_instagram_url(text: str):
    pattern = r"(https?://(www\.)?instagram\.com/[^\s]+)"
    match = re.search(pattern, text)
    return match.group(1) if match else None


async def download_with_ytdlp(url: str, temp_dir: str):
    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "cookiefile": get_cookies_file(),
        "format": "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)

    if not filepath.endswith(".mp4"):
        new_path = os.path.splitext(filepath)[0] + ".mp4"
        if os.path.exists(filepath):
            shutil.move(filepath, new_path)
        filepath = new_path

    return [filepath]


async def download_with_gallery_dl(url: str, temp_dir: str):
    cmd = [
        "gallery-dl",
        "--cookies", get_cookies_file(),
        "-d", temp_dir,
        url,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await proc.communicate()

    files = []
    for root, _, filenames in os.walk(temp_dir):
        for f in filenames:
            files.append(os.path.join(root, f))

    return sorted(files)


async def download_media(url: str, temp_dir: str):
    # First try gallery-dl (excellent for Instagram albums)
    files = await download_with_gallery_dl(url, temp_dir)
    if files:
        return files
    
    # Fallback to yt-dlp
    logger.info("gallery-dl returned no files, falling back to yt-dlp")
    try:
        return await download_with_ytdlp(url, temp_dir)
    except Exception as e:
        logger.error(f"Both downloaders failed: {e}")
        return []


def ensure_ios_compatible_video(input_path: str) -> str:
    if not input_path.lower().endswith((".mp4", ".mov")):
        return input_path

    output_path = os.path.splitext(input_path)[0] + "_ios.mp4"
    
    # Improved video filter: preserves aspect ratio + forces even dimensions
    vf = "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-movflags", "+faststart",
        "-threads", "2",
        "-y",
        output_path
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120
        )
        logger.info(f"✅ iOS-compatible re-encode succeeded: {output_path}")
        
        if os.path.exists(input_path) and input_path != output_path:
            try:
                os.unlink(input_path)
            except Exception:
                pass
        return output_path

    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg timeout for {input_path}")
        return input_path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed for {input_path}. Stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
        return input_path
    except Exception as e:
        logger.error(f"Unexpected error during ffmpeg re-encode for {input_path}: {e}")
        return input_path


# ---------- QUEUE WORKER ----------
async def worker():
    while True:
        update, context, url, status_msg = await queue.get()

        try:
            message = update.message

            await status_msg.edit_text("🔄 Downloading media from Instagram...")
            
            temp_dir = tempfile.mkdtemp()

            try:
                files = await download_media(url, temp_dir)

                if not files:
                    logger.warning(f"No media found in url: {url}.")
                    await status_msg.edit_text("❌ No media found in this link.")
                    continue

                # Single file
                if len(files) == 1:
                    file_path = files[0]
                    if file_path.lower().endswith(".mp4"):
                        file_path = ensure_ios_compatible_video(file_path)
                        await message.reply_video(
                            video=open(file_path, "rb"),
                            reply_to_message_id=message.message_id,
                            supports_streaming=True,
                        )
                    else:
                        await message.reply_photo(
                            photo=open(file_path, "rb"),
                            reply_to_message_id=message.message_id,
                        )
                else:
                    media_group = []
                    for f in files[:10]:  # Telegram limit
                        if f.lower().endswith(".mp4"):
                            media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            media_group.append(InputMediaPhoto(open(f, "rb")))

                    await message.reply_media_group(
                        media=media_group,
                        reply_to_message_id=message.message_id,
                    )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker error for {url}: {e}")
            try:
                await status_msg.edit_text("❌ Failed to process this link.")
            except:
                pass

        finally:
            # 30-second delay between downloads to reduce Instagram flagging
            await asyncio.sleep(30)
            queue.task_done()


# ---------- HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    # Extract ALL Instagram URLs from the message
    urls = re.findall(
        r"https?://(?:www\.)?instagram\.com/[^\s]+",
        update.message.text
    )
    if not urls:
        return

    # Remove duplicates while preserving order and limit per message
    urls = list(dict.fromkeys(urls))[:MAX_MEDIA_PER_MESSAGE]

    logger.info(f"Queued {len(urls)} Instagram link(s) from one message")

    for i, url in enumerate(urls, 1):
        if len(urls) == 1:
            status_text = "🔄 Downloading from Instagram..."
        else:
            status_text = f"🔄 Queued {i}/{len(urls)} — Downloading from Instagram..."

        status_msg = await update.message.reply_text(
            status_text,
            reply_to_message_id=update.message.message_id
        )

        await queue.put((update, context, url, status_msg))

    if len(urls) > 1:
        await update.message.reply_text(
            f"✅ Queued {len(urls)} Instagram reels. They will be processed one by one with delay.",
            reply_to_message_id=update.message.message_id
        )


# ---------- STARTUP ----------
async def on_startup(app):
    for _ in range(1):   # 1 worker + 30s delay = safer for Instagram
        asyncio.create_task(worker())


# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()