import os
import re
import tempfile
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

import instaloader

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

# Init Instaloader with safer settings
L = instaloader.Instaloader(
    download_pictures=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    request_timeout=10,
    quiet=True
)

# Instagram login (REQUIRED to avoid 403)
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")

if IG_USERNAME and IG_PASSWORD:
    try:
        L.login(IG_USERNAME, IG_PASSWORD)
        logger.info("Logged into Instagram")
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")

# ==============================
# HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message_text = update.message.text

    match = re.search(INSTAGRAM_REGEX, message_text)
    if not match:
        return

    url = match.group(0)
    user = update.message.from_user
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    try:
        shortcode = url.split("/")[4]  # more reliable extraction
        logger.info(f"Processing shortcode: {shortcode}")

        with tempfile.TemporaryDirectory() as temp_dir:

            post = instaloader.Post.from_shortcode(L.context, shortcode)

            # Ensure it's a video
            if not post.is_video:
                logger.warning("Post is not a video")
                return

            # Directly download video only (avoids 403 on other assets)
            video_url = post.video_url

            import requests
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.instagram.com/"
            }

            response = requests.get(video_url, headers=headers, stream=True)

            if response.status_code != 200:
                logger.error(f"Failed to download video: {response.status_code}")
                return

            video_path = os.path.join(temp_dir, f"{shortcode}.mp4")

            with open(video_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            # Delete original message
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning(f"Failed to delete message: {e}")

            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"

            with open(video_path, "rb") as vid:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vid,
                    caption=f"{user_mention} shared a video\n{url}",
                    parse_mode="HTML"
                )

            logger.info("Video sent successfully")

    except Exception as e:
        logger.error(f"Error processing message: {e}")


# ==============================
# MAIN
# ==============================

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
