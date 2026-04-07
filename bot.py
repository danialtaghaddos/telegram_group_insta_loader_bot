import os
import re
import tempfile
import logging
import requests

from telegram import Update
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

# ==============================
# INSTAGRAM SCRAPER (NO LOGIN, NO GRAPHQL)
# ==============================

def extract_video_url(instagram_url: str) -> str | None:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
        }

        # Force Instagram to return JSON (no GraphQL)
        url = instagram_url.split("?")[0] + "?__a=1&__d=dis"

        res = requests.get(url, headers=headers)

        if res.status_code != 200:
            logger.error(f"Metadata request failed: {res.status_code}")
            return None

        data = res.json()

        # Try multiple paths (Instagram changes structure often)
        try:
            return data["graphql"]["shortcode_media"]["video_url"]
        except:
            pass

        try:
            return data["items"][0]["video_versions"][0]["url"]
        except:
            pass

        logger.warning("Video URL not found in JSON")
        return None

    except Exception as e:
        logger.error(f"extract_video_url error: {e}")
        return None


# ==============================
# HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    match = re.search(INSTAGRAM_REGEX, update.message.text)
    if not match:
        return

    url = match.group(0)
    user = update.message.from_user
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    try:
        logger.info(f"Processing: {url}")

        video_url = extract_video_url(url)

        if not video_url:
            logger.warning("Failed to extract video URL")
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "video.mp4")

            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.instagram.com/"
            }

            r = requests.get(video_url, headers=headers, stream=True)

            if r.status_code != 200:
                logger.error(f"Video download failed: {r.status_code}")
                return

            with open(video_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            # Delete original message
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning(f"Delete failed: {e}")

            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"

            with open(video_path, "rb") as vid:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vid,
                    caption=f"{user_mention} shared a video\n{url}",
                    parse_mode="HTML"
                )

            logger.info("Video sent")

    except Exception as e:
        logger.error(f"Handler error: {e}")


# ==============================
# MAIN
# ==============================

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
