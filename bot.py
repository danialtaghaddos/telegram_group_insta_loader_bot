import os
import re
import asyncio
import logging
import tempfile
import shutil

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

import yt_dlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

queue = asyncio.Queue()

# ---------- UTIL ----------
def extract_instagram_url(text: str):
    pattern = r"(https?://(www\.)?instagram\.com/[^\s]+)"
    match = re.search(pattern, text)
    return match.group(1) if match else None


async def download_media(url: str, temp_dir: str):
    ydl_opts = {
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "quiet": True,
        "cookiefile": os.getenv("COOKIE_FILE", "cookies.txt"),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)

    return filepath


# ---------- QUEUE WORKER ----------
async def worker(app):
    while True:
        update, context, url = await queue.get()

        try:
            message = update.message

            await message.reply_text("Processing...")

            temp_dir = tempfile.mkdtemp()

            try:
                file_path = await download_media(url, temp_dir)

                if file_path.endswith(".mp4"):
                    await message.reply_video(
                        video=open(file_path, "rb"),
                        reply_to_message_id=message.message_id,
                    )
                else:
                    await message.reply_photo(
                        photo=open(file_path, "rb"),
                        reply_to_message_id=message.message_id,
                    )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Worker error: {e}")
            await update.message.reply_text("Failed to process link.")

        finally:
            queue.task_done()


# ---------- HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = extract_instagram_url(update.message.text)
    if not url:
        return

    logger.info(f"Queued: {url}")
    await queue.put((update, context, url))


# ---------- MAIN ----------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # start worker(s)
    for _ in range(2):  # concurrency
        asyncio.create_task(worker(app))

    logger.info("Bot started...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
