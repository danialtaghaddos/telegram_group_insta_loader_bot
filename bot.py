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
TMP_PATH = tempfile.gettempdir()

MAX_MEDIA_PER_MESSAGE = 5
queue: asyncio.Queue = asyncio.Queue(maxsize=30)


def get_file_size_mb(file_path: str) -> float:
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0.0

def get_cookies_file():
    """Returns Instagram cookies file (existing behavior)"""
    path = f"{TMP_PATH}/cookies.txt"
    
    if os.path.exists(path) and os.path.getsize(path) > 10:
        return path
    cookies = os.getenv("COOKIES_TXT")
    if not cookies or not cookies.strip():
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookies.strip())
        return path
    except Exception as e:
        logger.error(f"Failed to write Instagram cookies: {e}")
        return None


def get_facebook_cookies_file():
    """Writes Facebook cookies from env var if provided"""
    path = f"{TMP_PATH}/facebook_cookies.txt"
    
    if os.path.exists(path) and os.path.getsize(path) > 10:
        return path
    
    cookies = os.getenv("FACEBOOK_COOKIES_TXT")
    if not cookies or not cookies.strip():
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookies.strip())
        logger.info("Facebook cookies written from FACEBOOK_COOKIES_TXT")
        return path
    except Exception as e:
        logger.error(f"Failed to write Facebook cookies: {e}")
        return None


# ---------- UTIL ----------
def extract_social_urls(text: str):
    """Extract Instagram and Facebook URLs"""
    pattern = r"https?://(?:www\.)?(?:instagram\.com|facebook\.com|fb\.watch|fb\.com)/[^\s]+"
    urls = re.findall(pattern, text)
    return list(dict.fromkeys(urls))[:MAX_MEDIA_PER_MESSAGE]


def clean_facebook_url(url: str) -> str:
    """Clean Facebook share redirects"""
    if "facebook.com/share/" in url or "fb.watch" in url:
        match = re.search(r"facebook\.com/share/([a-zA-Z0-9]+)", url)
        if match:
            return f"https://www.facebook.com/share/{match.group(1)}/"
    return url


# ---------- DOWNLOAD FUNCTIONS ----------
async def download_with_ytdlp(url: str, temp_dir: str):
    is_facebook = "facebook.com" in url or "fb.watch" in url
    cookiefile = get_facebook_cookies_file() if is_facebook else get_cookies_file()

    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "cookiefile": cookiefile,
        "format": "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        "retries": 3,
        "fragment_retries": 3,
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
        "--cookies", get_cookies_file() or "",  # fallback to Instagram cookies
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
    url = clean_facebook_url(url)

    # Instagram: prefer gallery-dl
    if "instagram.com" in url:
        files = await download_with_gallery_dl(url, temp_dir)
        if files:
            return files
        logger.info("gallery-dl failed for Instagram, falling back to yt-dlp")

    # Facebook or fallback: use yt-dlp with platform-specific cookies
    try:
        return await download_with_ytdlp(url, temp_dir)
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return []


def get_video_metadata(file_path: str):
    """Use ffprobe to get width, height, and duration"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "v:0", "-show_entries",
            "stream=width,height,duration", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        import json
        data = json.loads(result.stdout)
        
        stream = data.get("streams", [{}])[0]
        width = stream.get("width", 720)
        height = stream.get("height", 1280)
        duration = int(float(stream.get("duration", 0))) if stream.get("duration") else 0
        
        return width, height, duration
    except Exception as e:
        logger.warning(f"Failed to get metadata for {file_path}: {e}")
        return 720, 1280, 0  # safe defaults for vertical video

def compress_video(input_path: str) -> str:
    if not input_path.lower().endswith((".mp4", ".mov")):
        return input_path

    output_path = os.path.splitext(input_path)[0] + "_ios.mp4"
    vf = "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "32",                    # Higher CRF = smaller size
        "-c:a", "aac",
        "-b:a", "96k",
        "-pix_fmt", "yuv420p",
        "-vf", "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease",
        "-movflags", "+faststart",
        "-threads", "2",
        "-y",
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
        logger.info(f"✅ iOS re-encode succeeded: {output_path}")
        if os.path.exists(input_path) and input_path != output_path:
            os.unlink(input_path)
        return output_path
    except subprocess.TimeoutExpired:
        logger.warning(f"ffmpeg timeout - skipping re-encode for {input_path}")
        return input_path
    except Exception as e:
        logger.error(f"ffmpeg re-encode failed: {e}")
        return input_path


# ---------- QUEUE WORKER ----------
async def worker():
    while True:
        update, context, url, status_msg = await queue.get()

        try:
            message = update.message
            platform = "Instagram" if "instagram.com" in url else "Facebook"

            try:
                await status_msg.edit_text(f"🔄 Downloading from {platform}...")
            except:
                pass

            temp_dir = tempfile.mkdtemp()

            try:
                files = await download_media(url, temp_dir)

                if not files:
                    logger.warning(f"No media found in url: {url}")
                    try:
                        await status_msg.edit_text(f"❌ Could not download from {platform}. (May need fresh cookies or be private)")
                    except:
                        pass
                    continue

                if len(files) == 1:
                    file_path = files[0]
                    if file_path.lower().endswith(".mp4"):
                        file_path = compress_video(file_path)
                        size_mb = get_file_size_mb(file_path)
                        width, height, duration = get_video_metadata(file_path)
                        await message.reply_video(
                            video=open(file_path, "rb"),
                            reply_to_message_id=message.message_id,
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
                            reply_to_message_id=message.message_id,
                        )
                else:
                    media_group = []
                    for f in files[:10]:
                        if f.lower().endswith(".mp4"):
                            media_group.append(InputMediaVideo(open(f, "rb")))
                        else:
                            media_group.append(InputMediaPhoto(open(f, "rb")))

                    await message.reply_media_group(
                        media=media_group,
                        reply_to_message_id=message.message_id,
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
                await status_msg.edit_text("❌ Failed to process this link.")
            except:
                pass

        finally:
            await asyncio.sleep(30)
            queue.task_done()


# ---------- HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    urls = extract_social_urls(update.message.text)
    if not urls:
        return

    logger.info(f"Queued {len(urls)} social link(s)")

    for i, url in enumerate(urls, 1):
        platform = "Instagram" if "instagram.com" in url else "Facebook"
        status_text = f"🔄 Downloading from {platform}..." if len(urls) == 1 else f"🔄 Queued {i}/{len(urls)} — Downloading from {platform}..."

        status_msg = await update.message.reply_text(
            status_text,
            reply_to_message_id=update.message.message_id
        )

        await queue.put((update, context, url, status_msg))


# ---------- STARTUP ----------
async def on_startup(app):
    for _ in range(1):
        asyncio.create_task(worker())


# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()