# bot/utils.py
import os, re
from contextlib import suppress

from .config import MAX_MEDIA_PER_MESSAGE

def extract_social_urls(text: str):
    # Extended pattern to include YouTube URLs
    pattern = (
        r"https?://(?:www\.)?"
        r"(?:instagram\.com|facebook\.com|fb\.watch|fb\.com|youtube\.com|m\.youtube\.com|youtu\.be)/[^\s]+"
    )
    urls = re.findall(pattern, text)

    # Filter out URLs that should be ignored
    filtered_urls = []
    for url in urls:
        url_lower = url.lower()

        # Skip Instagram live videos
        if 'instagram.com' in url_lower and '/live/' in url_lower:
            continue

        # Skip Instagram stories
        if 'instagram.com' in url_lower and '/stories/' in url_lower:
            continue

        # Skip Instagram user profiles (just username, no content path)
        if 'instagram.com' in url_lower:
            path_match = re.search(r'instagram\.com/([^\s?#]+)', url_lower)
            if path_match:
                full_path = path_match.group(1)
                if not re.search(r'(^|/)(reel|p|tv|reels)/', full_path):
                    continue

        # Skip Facebook stories
        if ('facebook.com' in url_lower or 'fb.com' in url_lower) and '/stories/' in url_lower:
            continue

        # Skip YouTube channels, user pages, playlists, and other non-video URLs
        # Handle both youtube.com and m.youtube.com (mobile)
        youtube_host = 'youtube.com' in url_lower or 'm.youtube.com' in url_lower
        if youtube_host or 'youtu.be' in url_lower:
            # youtu.be URLs are always valid (short URLs for specific videos)
            if 'youtu.be' in url_lower:
                pass  # Allow
            # youtube.com/watch?v= URLs are valid video URLs
            elif '/watch?v=' in url_lower or '/watch&v=' in url_lower:
                pass  # Allow
            # youtube.com/shorts/ URLs are valid short video URLs
            elif '/shorts/' in url_lower:
                pass  # Allow
            # youtube.com/embed/ URLs are valid embedded video URLs
            elif '/embed/' in url_lower:
                pass  # Allow
            else:
                # Skip channel pages, user pages, playlists, etc.
                continue

        filtered_urls.append(url)

    return list(dict.fromkeys(filtered_urls))[:MAX_MEDIA_PER_MESSAGE]

def get_file_size_mb(file_path: str) -> float:
    with suppress(Exception):
        return os.path.getsize(file_path) / (1024 * 1024)
    return 0.0


def compress_audio(input_path: str, target_bitrate: str = "96k") -> str:
    """
    Compress audio file using FFmpeg to reduce file size.
    
    Args:
        input_path: Path to the input audio file
        target_bitrate: Target bitrate for compression (e.g., "96k", "64k")
    
    Returns:
        Path to the compressed audio file, or original path if compression fails
    """
    import subprocess
    from .config import logger
    
    # Determine output extension based on input
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_compressed{ext}"
    
    # Map extensions to appropriate codecs
    if ext.lower() in ('.m4a', '.mp4'):
        codec = 'aac'
    elif ext.lower() == '.mp3':
        codec = 'libmp3lame'
    elif ext.lower() == '.opus':
        codec = 'libopus'
    elif ext.lower() == '.wav':
        codec = 'pcm_s16le'
    else:
        codec = 'aac'
    
    cmd = [
        "ffmpeg", "-i", input_path,
        "-b:a", target_bitrate,
        "-c:a", codec,
        "-ar", "44100",  # Standard sample rate
        "-ac", "2",      # Stereo
        "-y",            # Overwrite output file
        output_path
    ]
    
    try:
        logger.info(f"Compressing audio: {input_path} -> {output_path} (bitrate: {target_bitrate})")
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=120,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            original_size = get_file_size_mb(input_path)
            compressed_size = get_file_size_mb(output_path)
            logger.info(f"✅ Audio compressed: {original_size:.1f}MB -> {compressed_size:.1f}MB")
            
            # Remove original file to save space
            with suppress(Exception):
                os.unlink(input_path)
            
            return output_path
        else:
            logger.warning(f"FFmpeg compression failed for {input_path}")
            return input_path
            
    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg compression timeout for {input_path}")
        return input_path
    except Exception as e:
        logger.error(f"Audio compression error for {input_path}: {e}")
        return input_path
