import os
import re
import tempfile
import logging
import yt_dlp

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

        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts = {
                "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
                "format": "mp4",
                "quiet": True,
            }

            # Optional login if needed
            IG_USERNAME = os.getenv("IG_USERNAME")
            IG_PASSWORD = os.getenv("IG_PASSWORD")
            if IG_USERNAME and IG_PASSWORD:
                ydl_opts["username"] = IG_USERNAME
                ydl_opts["password"] = IG_PASSWORD

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_file = ydl.prepare_filename(info)

            # Delete original message
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning(f"Delete failed: {e}")

            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"

            with open(video_file, "rb") as vid:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=vid,
                    caption=f"{user_mention} shared a video\n{url}",
                    parse_mode="HTML"
                )

            logger.info("Video sent successfully")

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
