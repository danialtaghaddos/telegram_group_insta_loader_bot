# bot/utils.py
import os, re

from .config import MAX_MEDIA_PER_MESSAGE

def extract_social_urls(text: str):
    pattern = (
        r"https?://(?:www\.)?"
        r"(?:instagram\.com|facebook\.com|fb\.watch|fb\.com)/[^\s]+"
    )
    urls = re.findall(pattern, text)
    return list(dict.fromkeys(urls))[:MAX_MEDIA_PER_MESSAGE]

def get_file_size_mb(file_path: str) -> float:
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0.0