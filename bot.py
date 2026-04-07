import os
import re
import shutil
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

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Init instaloader
L = instaloader.Instaloader(
    download_pictures=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False
)

# Optional: login (recommended to avoid IG blocking)
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")

if IG_USERNAME and IG_PASSWORD:
    try:
        L.login(IG_USERNAME, IG_PASSWORD)
        logger.info("Logged into Instagram")
    except Exception as e:
        logger.warning(f"Instagram login failed: {e}")


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

    shortcode = None

    try:
        shortcode = url.split("/")[-2]
        logger.info(f"Processing shortcode: {shortcode}")

        # Create temp directory (auto-clean)
        with tempfile.TemporaryDirectory() as temp_dir:

            # Download post into temp dir
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=temp_dir)

            # Find video file
            video_file = None
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith(".mp4"):
                        video_file = os.path.join(root, file)
                        break

            if not video_file:
                logger.warning("No video found in post")
                return

            # Delete original message
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning(f"Failed to delete message: {e}")

            # Safe user mention
            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"

            # Send video
            with open(video_file, "rb") as vid:
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
