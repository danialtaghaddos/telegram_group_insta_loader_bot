# bot/config.py
import os
import asyncio
import logging
import tempfile
BOT_TOKEN = os.getenv("BOT_TOKEN")

TMP_PATH = tempfile.gettempdir()
MAX_MEDIA_PER_MESSAGE = 5

queue: asyncio.Queue = asyncio.Queue(maxsize=30)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)
