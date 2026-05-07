# bot/utils.py
import os, re

from .config import MAX_MEDIA_PER_MESSAGE

def extract_social_urls(text: str):
    pattern = (
        r"https?://(?:www\.)?"
        r"(?:instagram\.com|facebook\.com|fb\.watch|fb\.com)/[^\s]+"
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

        filtered_urls.append(url)

    return list(dict.fromkeys(filtered_urls))[:MAX_MEDIA_PER_MESSAGE]

def get_file_size_mb(file_path: str) -> float:
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0.0