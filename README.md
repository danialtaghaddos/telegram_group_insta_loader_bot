# Telegram Group Instagram Loader Bot

A Telegram bot that downloads and shares Instagram/Facebook/YouTube media in Telegram chats. The bot supports a moderator system allowing multiple users to manage bot activation in any chat they are a member of.

## Features

- 📸 **Download Instagram/Facebook Media** - Simply send Instagram or Facebook links in an activated chat to download and share media
- 🎵 **Download YouTube Audio** - When a YouTube link is shared, the bot asks if you want to download it as audio (MP3/M4A)
- 👥 **Moderator System** - Multiple moderators can manage bot activation in any chat they join
- 🚪 **Doorman Mode** - Automatically delete join/leave system messages to keep chats clean
- 🔐 **Access Control** - Admin can grant moderator access to trusted users
- 📝 **Access Requests** - Users can request moderator access via `/access` command

## Bot Commands

### For Regular Users

| Command | Description |
|---------|-------------|
| `/access` | Request moderator access. Submit a request to become a moderator (if enabled by admin) |
| `/help` | Show available commands based on your role |

### For Moderators

Moderators can activate/deactivate the bot and manage doorman settings in any chat they are a member of.

| Command | Description |
|---------|-------------|
| `/activate` | Activate the bot for the current chat |
| `/deactivate` | Deactivate the bot for the current chat |
| `/doorman` | Toggle doorman mode - auto-deletes join/leave system messages |
| `/myChats` | List chats you moderate (shows assigned chats, if any) |
| `/help` | Show all available commands |

### For Admin Only

| Command | Description |
|---------|-------------|
| `/listChats` | List all activated chats across the bot |
| `/listmods` | List all moderators with profile links |
| `/approve <user_id>` | Approve a pending moderator access request. Reply to the request notification or provide user ID |
| `/deny <user_id>` | Deny a pending moderator access request. Reply to the request notification or provide user ID |
| `/requests` | View all pending moderator access requests |
| `/access_enabled` | Enable access requests - allows users to use `/access` to request moderator access |
| `/access_disabled` | Disable access requests - users cannot request moderator access |
| `/addmod @username` | Manually add a user as moderator |
| `/removemod @username` | Remove a user as moderator |
| `/activate` | Activate the bot for the current chat (admin has access to all chats) |
| `/deactivate` | Deactivate the bot for the current chat (admin has access to all chats) |
| `/doorman` | Toggle doorman mode (admin has access to all chats) |

## How It Works

### Moderator Access Flow

1. **Request Access**: Users run `/access` to request moderator privileges (if enabled by admin)
2. **Admin Notification**: The admin receives a notification with the user's details
3. **Approval/Denial**: Admin uses `/approve` or `/deny` to respond to the request
4. **Moderator Permissions**: Once approved, the new moderator can manage the bot in any chat they are a member of

### Manual Moderator Addition

Admin can directly add moderators using:

```
/addmod @username
```

The new moderator will be able to activate/deactivate the bot in any chat they are a member of.

### Chat Activation

- **Admin**: Can activate/deactivate the bot in any chat
- **Moderators**: Can activate/deactivate the bot in any chat they are a member of
- Once activated, users in that chat can send Instagram/Facebook links to download media

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `ADMIN_USER_ID` | Your Telegram numeric user ID (the bot admin) |
| `DEBUG_BOT` | Set to enable debug mode (optional) |
| `TELEGRAM_API_ID` | Telegram API ID for Telethon (optional, enables username resolution) |
| `TELEGRAM_API_HASH` | Telegram API HASH for Telethon (optional, enables username resolution) |
| `TELEGRAM_SESSION_STRING` | Telethon session string (optional, for persistent sessions) |
| `YOUTUBE_AUDIO_FORMAT` | Audio format for YouTube downloads: `mp3` or `m4a` (default: `m4a`) |
| `COOKIES_TXT` | Instagram cookies in netscape format (optional, for private posts) |
| `FACEBOOK_COOKIES_TXT` | Facebook cookies in netscape format (optional, for private videos) |
| `YOUTUBE_COOKIES_TXT` | YouTube cookies in netscape format (optional, helps prevent 403 errors) |

**Note:** Setting `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` enables the bot to:

- Resolve any public username to user ID without requiring prior interaction with the bot
- Get chat links for private groups/channels in `/listChats`

To get your API credentials, visit [my.telegram.org](https://my.telegram.org).

### Obtaining Cookies (Optional)

Cookies help prevent 403 errors and allow downloading private/restricted content.

#### Getting YouTube Cookies

YouTube cookies are particularly useful for preventing 403 Forbidden errors when downloading videos.

1. Install a browser extension like "Get cookies.txt LOCALLY" (Chrome/Firefox)
2. Log in to YouTube in your browser
3. Use the extension to export cookies from youtube.com in Netscape format
4. Save the content and set it as the `YOUTUBE_COOKIES_TXT` environment variable

Alternatively, you can use yt-dlp to extract cookies:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt "https://www.youtube.com/watch?v=VIDEO_ID"
```

#### Getting Instagram/Facebook Cookies

Follow the same process for Instagram (instagram.com) or Facebook (facebook.com) content.

**Note:** Cookies are sensitive data. Keep them private and never share them publicly.

### Data Storage

The bot stores data in JSON files in the `/data` directory:

- `activated_chats.json` - List of chat IDs where the bot is activated
- `doorman_chats.json` - List of chat IDs with doorman mode enabled
- `moderators.json` - List of moderator user IDs
- `access_requests.json` - Access request history
- `settings.json` - Bot settings (e.g., access requests enabled/disabled)

## Deployment

### Docker

Build and run using Docker:

```bash
docker build -t insta-loader-bot .
docker run -e BOT_TOKEN=your_token -e ADMIN_USER_ID=your_user_id insta-loader-bot
```

### Docker Compose

```yaml
version: '3'
services:
  bot:
    build: .
    environment:
      - BOT_TOKEN=your_token
      - ADMIN_USER_ID=your_user_id
    volumes:
      - ./data:/data
```

### Direct Python

```bash
pip install -r requirements.txt
export BOT_TOKEN=your_token
export ADMIN_USER_ID=your_user_id
python -m bot.main
```

## Requirements

- Python 3.9+
- python-telegram-bot library
- Other dependencies in `requirements.txt`
- **FFmpeg** - Required for audio/video processing
- **Node.js** (optional but recommended) - JavaScript runtime for yt-dlp to properly extract YouTube formats

### Installing Dependencies

#### Ubuntu/Debian

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install FFmpeg
sudo apt-get install ffmpeg

# Install Node.js (recommended for YouTube support)
sudo apt-get install nodejs
```

#### macOS

```bash
# Install FFmpeg and Node.js via Homebrew
brew install ffmpeg node
```

#### Windows

- Download and install [FFmpeg](https://ffmpeg.org/download.html)
- Download and install [Node.js](https://nodejs.org/)
- Make sure both are added to your system PATH

## License
