# bot/config.py
import os
import asyncio
import logging
import tempfile
from dotenv import load_dotenv

# Load environment variables from .env.local or .env file
load_dotenv(".env.local")
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

TMP_PATH = tempfile.gettempdir()
MAX_MEDIA_PER_MESSAGE = 5

queue: asyncio.Queue = asyncio.Queue(maxsize=30)

# Track active downloads for cancellation
# Key: task_id (int), Value: dict with "cancelled" (bool), "temp_dir" (str or None), "status_msg" (Message)
active_tasks: dict[int, dict] = {}
_next_task_id: int = 1

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


def get_next_task_id() -> int:
    """Get the next unique task ID"""
    global _next_task_id
    task_id = _next_task_id
    _next_task_id += 1
    return task_id
