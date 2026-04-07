import re
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import instaloader

BOT_TOKEN = os.getenv("BOT_TOKEN")

L = instaloader.Instaloader()

INSTAGRAM_REGEX = r"(https?://(www\.)?instagram\.com/[^\s]+)"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text

    match = re.search(INSTAGRAM_REGEX, message)
    if not match:
        return

    url = match.group(0)
    user = update.message.from_user
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    try:
        shortcode = url.split("/")[-2]

        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

        video_file = None
        for file in os.listdir(shortcode):
            if file.endswith(".mp4"):
                video_file = os.path.join(shortcode, file)
                break

        if video_file:
            # Delete original message
            await context.bot.delete_message(chat_id, message_id)

            # Send video
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_file, "rb"),
                caption=f"@{user.username} shared a video\n{url}"
            )

        # cleanup
        for f in os.listdir(shortcode):
            os.remove(os.path.join(shortcode, f))
        os.rmdir(shortcode)

    except Exception as e:
        print(e)

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()
