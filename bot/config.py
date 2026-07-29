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
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

TMP_PATH = tempfile.gettempdir()
MAX_MEDIA_PER_MESSAGE = 5

queue: asyncio.Queue = asyncio.Queue(maxsize=30)

# Track active downloads for cancellation
# Key: task_id (int), Value: dict with "cancelled" (bool), "temp_dir" (str or None), "status_msg" (Message)
active_tasks: dict[int, dict] = {}
_next_task_id: int = 1


class UploadCancelledError(Exception):
    """Raised to unwind an in-progress Telethon upload when its task is cancelled."""


# Captions awaiting delivery once a large file forwarded via the admin's Telethon
# account has been copied into the target chat. Key: "{chat_id}:{status_msg_id}".
large_file_captions: dict[str, str] = {}

# Number of concurrent chunk uploads *per connection* used by the parallel
# Telethon uploader (see telethon_client.py) for files >10MB. Telethon's own
# upload_file() uploads chunks sequentially, which is the dominant bottleneck
# for large files; tunable here without a code change if 8 proves too
# aggressive for a single connection (empirically, pipelining deeper than
# ~8-16 on one connection plateaus or destabilizes it).
TELETHON_UPLOAD_WORKERS = int(os.getenv("TELETHON_UPLOAD_WORKERS", "16"))

# Number of separate MTProto TCP connections to open for large-file uploads.
# Pipelining more requests over a single connection plateaus (validated: 8
# and 16 gave the same throughput), since it's still one TCP flow — real
# parallelism needs independent connections, like official clients use.
TELETHON_UPLOAD_CONNECTIONS = int(os.getenv("TELETHON_UPLOAD_CONNECTIONS", "4"))

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
