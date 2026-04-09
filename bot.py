import os
import re
import tempfile
import logging
import yt_dlp
import instaloader

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
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception:
                pass

            user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
            caption = f"{user_mention} shared a post\n{url}"

            files = sorted(files)

            # ==============================
            # SINGLE
            # ==============================

            if len(files) == 1:
                file = files[0]
                with open(file, "rb") as f:
                    if file.endswith(".mp4"):
                        await context.bot.send_video(chat_id, f, caption=caption, parse_mode="HTML")
                    else:
                        await context.bot.send_photo(chat_id, f, caption=caption, parse_mode="HTML")
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

            await context.bot.send_media_group(chat_id, media=media_group)

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