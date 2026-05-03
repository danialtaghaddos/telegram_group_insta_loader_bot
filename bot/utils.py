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

        # Skip Instagram user profiles (just username, no other path)
        if 'instagram.com' in url_lower:
            # Extract path after instagram.com
            path_match = re.search(r'instagram\.com/([^/?#]+)', url_lower)
            if path_match:
                path = path_match.group(1)
                # If path doesn't contain / and isn't a known content type, skip it
                if '/' not in path and path not in ['reel', 'p']:
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