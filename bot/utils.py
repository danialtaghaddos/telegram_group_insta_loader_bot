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

def clean_facebook_url(url: str) -> str:
    if "facebook.com/share/" in url or "fb.watch" in url:
        match = re.search(r"facebook.com/share/([a-zA-Z0-9]+)", url)
        if match:
            return f"https://www.facebook.com/share/{match.group(1)}/"
    return url

def get_file_size_mb(file_path: str) -> float:
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0.0