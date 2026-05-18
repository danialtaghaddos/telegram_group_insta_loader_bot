# bot/downloaders.py
import os, shutil, asyncio, subprocess, yt_dlp, tempfile

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


async def download_youtube_audio(url: str, temp_dir: str, format: str = "m4a"):
    """Download YouTube video as audio file (MP3 or M4A)"""
    if format not in ("mp3", "m4a"):
        format = "m4a"
    
    logger.info(f"Downloading YouTube audio from {url} as {format.upper()}")
    
    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": False,  # Show warnings for debugging
        "format": "bestaudio/best",
        "extract_flat": False,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": format,
            "preferredquality": "192",
        }],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # After FFmpegExtractAudio postprocessor, the extension changes
            expected_ext = format
            filepath = os.path.splitext(ydl.prepare_filename(info))[0] + f".{expected_ext}"
            
            logger.info(f"Looking for audio file at: {filepath}")
            
            # If the expected file doesn't exist, try to find the actual output
            if not os.path.exists(filepath):
                # yt-dlp might have created a file with a different extension
                base_path = os.path.splitext(ydl.prepare_filename(info))[0]
                logger.info(f"Expected file not found, searching in: {base_path}.*")
                for ext in [expected_ext, "m4a", "mp3", "webm", "opus", "m4a"]:
                    test_path = f"{base_path}.{ext}"
                    if os.path.exists(test_path):
                        filepath = test_path
                        logger.info(f"Found audio file: {filepath}")
                        break
            
            if os.path.exists(filepath):
                logger.info(f"Successfully downloaded audio: {filepath}")
                return [filepath]
            else:
                logger.error(f"Audio file not found after download. Expected: {filepath}")
                # List files in temp_dir for debugging
                files_in_dir = os.listdir(temp_dir)
                logger.error(f"Files in temp dir: {files_in_dir}")
                return []
    except Exception as e:
        logger.error(f"YouTube audio download error for {url}: {e}")
        raise


async def download_media(url: str, temp_dir: str):
    # YouTube: download as audio
    if "youtube.com" in url or "youtu.be" in url:
        try:
            # Default to M4A format for better quality
            audio_format = os.getenv("YOUTUBE_AUDIO_FORMAT", "m4a").lower()
            if audio_format not in ("mp3", "m4a"):
                audio_format = "m4a"
            return await download_youtube_audio(url, temp_dir, audio_format)
        except Exception as e:
            logger.error(f"YouTube audio download failed for {url}: {e}")
            return []

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
