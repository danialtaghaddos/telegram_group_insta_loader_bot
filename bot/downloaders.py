# bot/downloaders.py
import os, shutil, asyncio, subprocess, yt_dlp, tempfile

from .utils import clean_facebook_url
from .config import logger

TMP_PATH = tempfile.gettempdir()

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
        return path
    except Exception as e:
        logger.error(f"Failed to write Facebook cookies: {e}")
        return None

async def download_with_ytdlp(url: str, temp_dir: str):
    is_facebook = "facebook.com" in url or "fb.watch" in url
    cookiefile = get_facebook_cookies_file() if is_facebook else get_cookies_file()

    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "cookiefile": cookiefile,
        "format": (
            "bv*[filesize_approx<=50M]/"
            "bv*[height<=720]/"
            "best"
        ),
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
