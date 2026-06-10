# bot/downloaders.py
import os, shutil, asyncio, subprocess, yt_dlp, tempfile
import re
import json
import requests as requests_module

from .config import logger
from .storage import (
    load_instagram_cookies,
    load_facebook_cookies,
    load_youtube_cookies,
)

TMP_PATH = tempfile.gettempdir()


def _shortcode_to_pk(shortcode: str) -> int:
    """Convert Instagram shortcode to numeric ID (pk)"""
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    pk = 0
    for c in shortcode:
        pk = pk * 64 + chars.index(c)
    return pk


def _extract_instagram_caption_from_page(url: str) -> str:
    """
    Fallback method to extract Instagram caption using Instagram's API directly.
    This handles photo-only posts that yt-dlp cannot process.
    Uses cookies for authentication.
    """
    try:
        # Extract shortcode from URL
        # URLs can be: instagram.com/p/SHORTCODE/, instagram.com/reel/SHORTCODE/, etc.
        match = re.search(r'(?:instagram\.com)/(?:p|reel|tv)/([A-Za-z0-9_-]+)', url)
        if not match:
            logger.debug("Could not extract shortcode from URL")
            return ""
        shortcode = match.group(1)
        
        # Get cookies for authentication
        cookiefile = get_instagram_cookies_file()
        if not cookiefile or not os.path.exists(cookiefile):
            logger.debug("No cookies file available for API access")
            return ""
        
        # Parse cookies from Netscape format file
        cookies_dict = {}
        with open(cookiefile, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        domain = parts[0]
                        name = parts[5]
                        value = parts[6] if len(parts) > 6 else ''
                        if '.instagram.com' in domain:
                            cookies_dict[name] = value
        
        if not cookies_dict:
            logger.debug("No Instagram cookies found")
            return ""
        
        # Method 1: Try the Instagram Media API (simpler, works for most posts)
        pk = _shortcode_to_pk(shortcode)
        api_url = f'https://i.instagram.com/api/v1/media/{pk}/info/'
        headers = {
            "User-Agent": "Instagram 275.0.0.27.94 Android (30/11; 320dpi; 720x1280; Xiaomi; Redmi 4X; santoni; qcom; en_US; 458220556)",
            "X-IG-App-ID": "936619743392459",
            "X-IG-WWW-Claim": "0",
            "X-ASBD-ID": "198387",
            "Accept-Language": "en-US",
            "Accept": "*/*",
        }
        
        try:
            response = requests_module.get(api_url, headers=headers, cookies=cookies_dict, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok' and data.get('items'):
                    item = data['items'][0]
                    caption = item.get('caption', {}).get('text', '')
                    if caption:
                        return caption
        except Exception as e:
            logger.debug(f"Media API failed: {e}")
        
        # Method 2: Try the GraphQL query (more reliable, used by yt-dlp)
        csrf_token = cookies_dict.get('csrftoken', '')
        graphql_url = 'https://www.instagram.com/graphql/query/'
        
        variables = {
            'shortcode': shortcode,
            'child_comment_count': 3,
            'fetch_comment_count': 40,
            'parent_comment_count': 24,
            'has_threaded_comments': True,
        }
        
        params = {
            'doc_id': '8845758582119845',
            'variables': json.dumps(variables, separators=(',', ':')),
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "X-IG-WWW-Claim": "0",
            "X-ASBD-ID": "198387",
            "X-CSRFToken": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
            "Accept": "application/json, text/plain, */*",
        }
        
        try:
            response = requests_module.get(graphql_url, headers=headers, cookies=cookies_dict, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                caption_data = data.get('data', {}).get('xdt_shortcode_media', {})
                caption = caption_data.get('edge_media_to_caption', {}).get('edges', [{}])[0].get('node', {}).get('text', '')
                if caption:
                    return caption
        except Exception as e:
            logger.debug(f"GraphQL API failed: {e}")
        
        logger.debug("No caption found via API methods")
        return ""
        
    except Exception as e:
        logger.debug(f"Failed to extract caption from page: {e}")
        return ""


async def fetch_instagram_caption(url: str) -> str:
    """Fetch the caption/description from an Instagram post"""
    caption = ""
    
    # Method 1: Try yt-dlp first (works for videos and carousels)
    try:
        cookiefile = get_instagram_cookies_file()
        
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiefile": cookiefile,
            "extract_flat": False,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }
        
        def _extract_with_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("description", "")
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        caption = await loop.run_in_executor(None, _extract_with_ytdlp)
        
        if caption:
            logger.info(f"Fetched Instagram caption via yt-dlp: {caption[:50]}...")
            return caption
            
    except Exception as e:
        error_msg = str(e)
        # Check if it's a photo-only post error - these are expected for non-video posts
        # yt-dlp raises various errors for photo posts: "no video", "No video formats found", etc.
        if any(keyword in error_msg.lower() for keyword in ['no video', 'there is no video', 'no video formats']):
            logger.debug(f"yt-dlp: Photo-only post detected, trying fallback method: {error_msg}")
        else:
            logger.warning(f"yt-dlp caption fetch failed: {error_msg}")
    
    # Method 2: Fallback to direct page scraping for photo posts
    if not caption:
        try:
            logger.debug("Trying fallback caption extraction...")
            caption = await asyncio.get_event_loop().run_in_executor(
                None, _extract_instagram_caption_from_page, url
            )
            if caption:
                logger.info(f"Fetched Instagram caption via fallback: {caption[:50]}...")
        except Exception as e:
            logger.warning(f"Fallback caption fetch failed: {e}")
    
    return caption or ""

def get_instagram_cookies_file():
    """Returns Instagram cookies file, loading from Google Drive storage."""
    path = f"{TMP_PATH}/instagram_cookies.txt"
    
    # Check if file already exists and is valid
    if os.path.exists(path) and os.path.getsize(path) > 10:
        return path
    
    # Load cookies from Google Drive storage
    cookies = load_instagram_cookies()
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
    """Returns Facebook cookies file, loading from Google Drive storage."""
    path = f"{TMP_PATH}/facebook_cookies.txt"
    
    # Check if file already exists and is valid
    if os.path.exists(path) and os.path.getsize(path) > 10:
        return path
    
    # Load cookies from Google Drive storage
    cookies = load_facebook_cookies()
    if not cookies or not cookies.strip():
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookies.strip())
        return path
    except Exception as e:
        logger.error(f"Failed to write Facebook cookies: {e}")
        return None


def get_youtube_cookies_file():
    """Returns YouTube cookies file, loading from Google Drive storage."""
    path = f"{TMP_PATH}/youtube_cookies.txt"
    
    # Check if file already exists and is valid
    if os.path.exists(path) and os.path.getsize(path) > 10:
        return path
    
    # Load cookies from Google Drive storage
    cookies = load_youtube_cookies()
    if not cookies or not cookies.strip():
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookies.strip())
        return path
    except Exception as e:
        logger.error(f"Failed to write YouTube cookies: {e}")
        return None

async def download_with_ytdlp(url: str, temp_dir: str):
    is_facebook = "facebook.com" in url or "fb.watch" in url
    cookiefile = get_facebook_cookies_file() if is_facebook else get_instagram_cookies_file()

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
        "--cookies", get_instagram_cookies_file() or "",  # fallback to Instagram cookies
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
    
    # Get YouTube cookies file to prevent 403 errors
    cookiefile = get_youtube_cookies_file()
    
    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": False,  # Show warnings for debugging
        "cookiefile": cookiefile,  # Use YouTube cookies if available
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
    url_lower = url.lower()
    if "youtube.com" in url_lower or "m.youtube.com" in url_lower or "youtu.be" in url_lower:
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
        files = await download_with_ytdlp(url, temp_dir)
        return files
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return []
