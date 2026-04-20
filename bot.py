import os
import re
import tempfile
import logging
import yt_dlp
import instaloader
import asyncio

from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# ==============================
# CONFIG
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
INSTAGRAM_REGEX = r"(https?://(www\.)?instagram\.com/[^\s]+)"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)
job_queue = asyncio.Queue()

# ==============================
# COOKIES
# ==============================
def write_cookies_file():
    cookies = os.getenv("COOKIES_TXT")
    if not cookies:
        return None

    path = "/tmp/cookies.txt"
    with open(path, "w") as f:
        f.write(cookies)

    return path

# ==============================
# INSTALOADER SETUP
# ==============================
def get_instaloader():
    L = instaloader.Instaloader(
        dirname_pattern="/tmp",
        save_metadata=False,
        download_comments=False,
        post_metadata_txt_pattern=""
    )

    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")

    if username and password:
        try:
            L.login(username, password)
        except Exception as e:
            logger.warning(f"Login failed: {e}")

    return L

# ==============================
# DOWNLOAD VIA INSTALOADER
# ==============================
def download_instagram_post(url, temp_dir):
    shortcode = url.split("/p/")[-1].split("/")[0]

    L = get_instaloader()

    post = instaloader.Post.from_shortcode(L.context, shortcode)

    L.dirname_pattern = temp_dir
    L.download_post(post, target=shortcode)

    files = []
    for f in os.listdir(temp_dir):
        path = os.path.join(temp_dir, f)
        if path.endswith((".jpg", ".mp4")):
            files.append(path)

    return files

# ==============================
# yt-dlp (REELS)
# ==============================
def download_with_ytdlp(url, temp_dir):
    cookies_path = write_cookies_file()

    ydl_opts = {
        "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
        "quiet": True,
    }
    
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    files = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        for f in os.listdir(temp_dir):
            path = os.path.join(temp_dir, f)
            if os.path.isfile(path):
                files.append(path)

    except Exception as e:
        logger.warning(f"yt-dlp failed: {e}")

    return files

# ==============================
# HANDLER
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, job):
    if not update.message or not update.message.text:
        return

    match = re.search(INSTAGRAM_REGEX, update.message.text)
    if not match:
        return

    url = match.group(0)
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    await job_queue.put({
        "url": url,
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
    })

# ==============================
# QUEUE_PROCESSOR
# ==============================
async def process_job(context: ContextTypes.DEFAULT_TYPE, job):
    url = job["url"]
    chat_id = job["chat_id"]
    message_id = job["message_id"]
    try:
        logger.info(f"Processing: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:

            # ==============================
            # ROUTE BASED ON URL TYPE
            # ==============================
            if "/reel/" in url:
                files = download_with_ytdlp(url, temp_dir)
            else:
                files = download_instagram_post(url, temp_dir)

            if not files:
                logger.warning("No media found")
                return

            # Delete original message
            caption = f"Instagram video from {url} ✔"
            files = sorted(files)

            # ==============================
            # SINGLE
            # ==============================
            if len(files) == 1:
                file = files[0]
                with open(file, "rb") as f:
                    if file.endswith(".mp4"):
                        await context.bot.send_video(chat_id, f, caption=caption, reply_to_message_id=message_id, parse_mode="HTML")
                    else:
                        await context.bot.send_photo(chat_id, f, caption=caption, reply_to_message_id=message_id, parse_mode="HTML")
                return

            # ==============================
            # CAROUSEL
            # ==============================
            media_group = []

            for i, file in enumerate(files[:10]):
                with open(file, "rb") as f:
                    if file.endswith(".mp4"):
                        media = InputMediaVideo(
                            media=f.read(),
                            caption=caption if i == 0 else None,
                            parse_mode="HTML"
                        )
                    else:
                        media = InputMediaPhoto(
                            media=f.read(),
                            caption=caption if i == 0 else None,
                            parse_mode="HTML"
                        )
                    media_group.append(media)

            await context.bot.send_media_group(chat_id, media=media_group, reply_to_message_id=message_id)

    except Exception as e:
        logger.error(f"Handler error: {e}")

# ==============================
# BACKGROUND_WORKER
# ==============================
async def worker(app):
    while True:
        job = await job_queue.get()

        try:
            await process_job(app, job)
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            job_queue.task_done()
# ==============================
# MAIN
# ==============================
async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

   # Start workers
    async def start_workers(app):
        for _ in range(1):  # 🔥 number of parallel workers
            asyncio.create_task(worker(app))

    app.post_init = start_workers

    logger.info("Bot started...")
    
    await app.run_polling()


if __name__ == "__main__":
    main()
