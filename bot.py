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

queue = asyncio.Queue()

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
    
    # Fallback to yt-dlp (better for some Reels or when gallery-dl fails)
    logger.info("gallery-dl returned no files, falling back to yt-dlp")
    try:
        return await download_with_ytdlp(url, temp_dir)
    except Exception as e:
        logger.error(f"Both downloaders failed: {e}")
        return []

def ensure_ios_compatible_video(filepath: str) -> str:
    if not filepath.endswith(".mp4"):
        return filepath
    
    output_path = filepath.replace(".mp4", "_ios.mp4")
    cmd = [
        "ffmpeg", "-i", filepath,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",          # Most compatible pixel format
        "-movflags", "+faststart",      # Better streaming
        "-vf", "scale='iw:ih'",         # Keep original resolution
        "-y", output_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path
    except:
        return filepath  # fallback to original

# ---------- QUEUE WORKER ----------
async def worker():
    while True:
        update, context, url = await queue.get()

        try:
            message = update.message

            temp_dir = tempfile.mkdtemp()

            try:
                files = await download_media(url, temp_dir)

                if not files:
                    logger.warning(f"No media found in url: {url}.")
                    continue

                # Single file
                if len(files) == 1:
                    file_path = files[0]
                    if file_path.endswith(".mp4"):
                        await message.reply_video(
                            video=open(file_path, "rb"),
                            reply_to_message_id=message.message_id,
                        )
                    else:
                        await message.reply_photo(
                            photo=open(file_path, "rb"),
                            reply_to_message_id=message.message_id,
                        )
                else:
                    media_group = []
                    for f in files[:10]:  # Telegram limit
                        if f.endswith(".mp4"):
                            media_group.append(InputMediaVideo(open(ensure_ios_compatible_video(f), "rb")))
                        else:
                            media_group.append(InputMediaPhoto(open(ensure_ios_compatible_video(f), "rb")))

                    await message.reply_media_group(
                        media=media_group,
                        reply_to_message_id=message.message_id,
                    )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker error: {e}")

        finally:
            queue.task_done()


# ---------- HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = extract_instagram_url(update.message.text)
    if not url:
        return

    logger.info(f"Queued: {url}")
    await queue.put((update, context, url))


# ---------- STARTUP ----------
async def on_startup(app):
    for _ in range(2):
        asyncio.create_task(worker())


# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
