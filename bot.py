import os
import re
import tempfile
import logging
import requests
import yt_dlp

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
# FALLBACK SCRAPER (IMAGES)
# ==============================

def fallback_extract_images(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
        }

        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            return []

        html = res.text

        # Extract og:image
        matches = re.findall(r'property="og:image" content="([^"]+)"', html)

        return list(set(matches))

    except Exception as e:
        logger.error(f"Fallback error: {e}")
        return []

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
            cookies_path = write_cookies_file()

            ydl_opts = {
                "outtmpl": os.path.join(temp_dir, "%(id)s_%(index)s.%(ext)s"),
                "quiet": True,
                "ignoreerrors": True,
            }

            if cookies_path:
                ydl_opts["cookiefile"] = cookies_path

            files = []

            # ==============================
            # TRY yt-dlp FIRST
            # ==============================

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)

                for f in os.listdir(temp_dir):
                    path = os.path.join(temp_dir, f)
                    if os.path.isfile(path):
                        files.append(path)

            except Exception as e:
                logger.warning(f"yt-dlp failed: {e}")

            # ==============================
            # FALLBACK (IMAGES ONLY)
            # ==============================

            if not files:
                logger.info("Using fallback scraper")

                image_urls = fallback_extract_images(url)

                for i, img_url in enumerate(image_urls):
                    img_path = os.path.join(temp_dir, f"img_{i}.jpg")
                    r = requests.get(img_url)
                    if r.status_code == 200:
                        with open(img_path, "wb") as f:
                            f.write(r.content)
                        files.append(img_path)

            if not files:
                logger.warning("No media found at all")
                return

            # ==============================
            # DELETE ORIGINAL MESSAGE
            # ==============================

            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning(f"Delete failed: {e}")

            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
            caption = f"{user_mention} shared a post\n{url}"

            files = sorted(files)

            # ==============================
            # SEND SINGLE
            # ==============================

            if len(files) == 1:
                file = files[0]
                with open(file, "rb") as f:
                    if file.endswith(".mp4"):
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=f,
                            caption=caption,
                            parse_mode="HTML"
                        )
                    else:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=caption,
                            parse_mode="HTML"
                        )
                return

            # ==============================
            # SEND CAROUSEL
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

            await context.bot.send_media_group(chat_id=chat_id, media=media_group)

            logger.info("Media sent successfully")

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
