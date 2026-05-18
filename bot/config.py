# bot/config.py
import os
import asyncio
import logging
import tempfile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

TMP_PATH = tempfile.gettempdir()
MAX_MEDIA_PER_MESSAGE = 5

# Cache configuration
CACHE_DIR = os.getenv('CACHE_DIR', '/data/tg_media_cache')
CACHE_TTL_HOURS = int(os.getenv('CACHE_TTL_HOURS', '24'))
CACHE_CLEANUP_INTERVAL_MINUTES = int(os.getenv('CACHE_CLEANUP_INTERVAL_MINUTES', '60'))
CACHE_ENABLE_FORWARDING = os.getenv('CACHE_ENABLE_FORWARDING', 'true').lower() in ('1', 'true', 'yes')

queue: asyncio.Queue = asyncio.Queue(maxsize=30)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)
