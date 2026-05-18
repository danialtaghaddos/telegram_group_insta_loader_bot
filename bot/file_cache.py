# bot/file_cache.py
import os
import json
import time
import shutil
import hashlib
import asyncio
from pathlib import Path
from .config import logger, CACHE_DIR, CACHE_TTL_HOURS, CACHE_CLEANUP_INTERVAL_MINUTES

def get_cache_dir() -> str:
    """Return the cache directory, creating it if needed."""
    cache_dir = CACHE_DIR
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as e:
        logger.warning(f"Failed to create cache directory {cache_dir}: {e}")
    return cache_dir

def get_cache_key(url: str) -> str:
    """Compute a safe filesystem key from a URL using SHA256."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()

def _get_entry_dir(url: str) -> str:
    """Return the directory path for a cache entry."""
    return os.path.join(get_cache_dir(), get_cache_key(url))

def _get_metadata_path(url: str) -> str:
    """Return the path to the metadata.json for a cache entry."""
    return os.path.join(_get_entry_dir(url), "metadata.json")

def is_cache_valid(url: str, ttl_seconds: int = None) -> bool:
    """Check if a valid cache entry exists for the given URL."""
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    meta_path = _get_metadata_path(url)
    if not os.path.isfile(meta_path):
        return False
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        created_at = meta.get('created_at', 0)
        if time.time() - created_at < ttl_seconds:
            return True
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cache metadata read error for {url}: {e}")
    return False

def get_cache_metadata(url: str) -> dict | None:
    """Retrieve the full metadata for a cache entry, or None if invalid."""
    meta_path = _get_metadata_path(url)
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cache metadata read error for {url}: {e}")
        return None

def restore_cache_to_temp(url: str, temp_dir: str) -> list[str] | None:
    """If cache is valid, copy cached files into temp_dir and return file paths.
    Returns None if cache is invalid or missing files."""
    if not is_cache_valid(url):
        return None
    meta = get_cache_metadata(url)
    if not meta or 'files' not in meta:
        return None
    entry_dir = _get_entry_dir(url)
    restored_files = []
    for fname in meta['files']:
        src = os.path.join(entry_dir, fname)
        if not os.path.isfile(src):
            logger.warning(f"Cache file missing: {src}")
            return None
        dst = os.path.join(temp_dir, fname)
        try:
            shutil.copy2(src, dst)
            restored_files.append(dst)
        except Exception as e:
            logger.error(f"Failed to copy cache file {src} -> {dst}: {e}")
            return None
    logger.info(f"Restored {len(restored_files)} cached file(s) for {url}")
    return restored_files

def add_cache_entry(url: str, src_files: list[str], last_upload: dict = None):
    """Add or update a cache entry. src_files are paths to files to cache.
    last_upload is optional dict with {"chat_id": int, "message_ids": [int, ...]}."""
    entry_dir = _get_entry_dir(url)
    try:
        os.makedirs(entry_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create cache entry dir {entry_dir}: {e}")
        return
    # Copy files into cache entry dir
    cached_names = []
    for fpath in src_files:
        if not os.path.isfile(fpath):
            logger.warning(f"Source file missing for cache: {fpath}")
            continue
        fname = os.path.basename(fpath)
        # Avoid name collisions by prefixing with index if needed
        dst = os.path.join(entry_dir, fname)
        if os.path.exists(dst):
            base, ext = os.path.splitext(fname)
            idx = 1
            while os.path.exists(dst):
                dst = os.path.join(entry_dir, f"{base}_{idx}{ext}")
                idx += 1
            fname = os.path.basename(dst)
        try:
            shutil.copy2(fpath, dst)
            cached_names.append(fname)
        except Exception as e:
            logger.error(f"Failed to copy file to cache {fpath} -> {dst}: {e}")
    if not cached_names:
        logger.warning(f"No files cached for {url}")
        return
    # Write metadata atomically
    meta = {
        "url": url,
        "created_at": time.time(),
        "files": cached_names,
    }
    if last_upload:
        meta["last_upload"] = last_upload
    meta_path = _get_metadata_path(url)
    tmp_path = meta_path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp_path, meta_path)
        logger.info(f"Added cache entry for {url} ({len(cached_names)} files)")
    except Exception as e:
        logger.error(f"Failed to write cache metadata for {url}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def cleanup_expired(ttl_seconds: int = None) -> int:
    """Remove expired cache entries. Returns number of entries removed."""
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    cache_dir = get_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0
    removed = 0
    now = time.time()
    for entry_name in os.listdir(cache_dir):
        entry_dir = os.path.join(cache_dir, entry_name)
        if not os.path.isdir(entry_dir):
            continue
        meta_path = os.path.join(entry_dir, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            created_at = meta.get('created_at', 0)
            if now - created_at >= ttl_seconds:
                shutil.rmtree(entry_dir, ignore_errors=True)
                removed += 1
        except Exception as e:
            logger.warning(f"Error cleaning up cache entry {entry_dir}: {e}")
    if removed:
        logger.info(f"Cleaned up {removed} expired cache entries")
    return removed

async def cleanup_loop(ttl_seconds: int = None, interval_minutes: int = None):
    """Background coroutine that periodically cleans up expired cache entries."""
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    if interval_minutes is None:
        interval_minutes = CACHE_CLEANUP_INTERVAL_MINUTES
    interval_seconds = max(interval_minutes * 60, 60)  # at least 1 minute
    # Initial cleanup after a short delay
    await asyncio.sleep(5)
    while True:
        try:
            cleanup_expired(ttl_seconds)
        except Exception as e:
            logger.error(f"Error in cache cleanup loop: {e}")
        await asyncio.sleep(interval_seconds)

def start_cleanup_loop(loop=None):
    """Schedule the cleanup loop on the given event loop (or the running loop if None)."""
    if loop is None:
        loop = asyncio.get_running_loop()
    loop.create_task(cleanup_loop())