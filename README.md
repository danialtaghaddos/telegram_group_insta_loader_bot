# Telegram Group Instagram Loader Bot

A Telegram bot that downloads and shares Instagram/Facebook/YouTube media in Telegram chats. The bot supports a moderator system allowing multiple users to manage bot activation in any chat they are a member of.

## Features

- 📸 **Download Instagram/Facebook Media** - Simply send Instagram or Facebook links in an activated chat to download and share media
- 📝 **Instagram Captions** - Automatically fetches and includes Instagram post captions with the shared media
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
| `/listMods` | List all moderators with profile links |
| `/approve <user_id>` | Approve a pending moderator access request. Reply to the request notification or provide user ID |
| `/deny <user_id>` | Deny a pending moderator access request. Reply to the request notification or provide user ID |
| `/requests` | View all pending moderator access requests |
| `/addMods @username` | Manually add a user as moderator |
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

```txt
/addMods @username
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
| `GOOGLE_DRIVE_FOLDER_ID` | Google Drive folder ID for cloud storage (required) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to Google service account JSON key file (default: `gc-service.json`) |

**Note:** Setting `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` enables the bot to:

- Resolve any public username to user ID without requiring prior interaction with the bot
- Get chat links for private groups/channels in `/listChats`

To get your API credentials, visit [my.telegram.org](https://my.telegram.org).

### Obtaining Cookies (Optional but Recommended)

Cookies help prevent 403 errors and allow downloading private/restricted content. The bot loads cookies from Google Drive storage - simply upload your cookies files to the configured Google Drive folder.

#### Step 1: Export Cookies from Your Browser

**For YouTube (prevents 403 Forbidden errors):**

1. Install a browser extension like "Get cookies.txt LOCALLY" (Chrome/Firefox)
2. Log in to YouTube in your browser
3. Use the extension to export cookies from youtube.com in Netscape format
4. Save the exported content

**For Instagram (enables private post downloads):**

1. Log in to Instagram in your browser
2. Use the same extension to export cookies from instagram.com
3. Save the exported content

**For Facebook (enables private video downloads):**

1. Log in to Facebook in your browser
2. Use the same extension to export cookies from facebook.com
3. Save the exported content

Alternatively, you can use yt-dlp to extract cookies:

```bash
# YouTube cookies
yt-dlp --cookies-from-browser chrome --cookies youtube_cookies.txt "https://www.youtube.com/watch?v=VIDEO_ID"

# Instagram cookies
yt-dlp --cookies-from-browser chrome --cookies instagram_cookies.txt "https://www.instagram.com/p/POST_ID/"
```

#### Step 2: Upload Cookies to Google Drive

Upload your cookies files to the Google Drive folder configured in `GOOGLE_DRIVE_FOLDER_ID`:

| File Name | Purpose |
|-----------|---------|
| `instagram_cookies.txt` | Instagram cookies for private post downloads |
| `facebook_cookies.txt` | Facebook cookies for private video downloads |
| `youtube_cookies.txt` | YouTube cookies to prevent 403 errors |

**Important Notes:**

- The bot requires `GOOGLE_DRIVE_FOLDER_ID` to be configured for cookies to work
- Cookies are sensitive data. Keep them private and never share them publicly
- Refresh your cookies periodically as they may expire
- Make sure the cookies are in Netscape format (tab-separated values)

### Data Storage

The bot uses Google Drive for cloud storage when configured. If cloud storage is not configured, it falls back to local JSON files so activation state still persists between restarts.

#### Google Drive Cloud Storage (Recommended)

The bot stores data as JSON files in a Google Drive folder. This provides unlimited reads/writes without the request limitations of JSONBin.io.

**Setup Steps:**

1. **Create a Google Cloud Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one

2. **Enable Google Drive API**
   - In your project, go to "APIs & Services" > "Library"
   - Search for "Google Drive API" and enable it

3. **Create a Service Account**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Give it a name (e.g., "telegram-bot") and create
   - Go to the service account details, click "Keys" > "Add Key" > "Create new key"
   - Select JSON format and download the key file
   - Save the file as `gc-service.json` in your project root

4. **Share the Google Drive Folder**
   - **Important**: The folder must be in a **Shared Drive** (not My Drive) because service accounts don't have their own storage quota
   - Create a Shared Drive in Google Workspace (admin required) or use an existing one
   - Create a folder in the Shared Drive (or use an existing one)
   - Get the folder ID from the URL: `https://drive.google.com/drive/folders/FOLDER_ID`
   - Share the folder with the service account email (found in the JSON key file)
   - Give it **Editor** permissions

5. **Configure Environment Variables**

   ```bash
   GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
   GOOGLE_SERVICE_ACCOUNT_FILE=gc-service.json
   ```

The bot will automatically create the following files in your Google Drive folder:

- `activated_chats.json` - List of activated chat IDs
- `doorman_chats.json` - List of chats with doorman mode enabled
- `moderators.json` - Moderator permissions data

#### Local Storage (Fallback)

If Google Drive is not configured, local state is stored under `data/` by default. You can override that directory with `BOT_STORAGE_DIR`.

#### Notes

- Each read and write goes directly to Google Drive when cloud storage is configured.
- Local fallback uses plain JSON files and keeps `/activate`, `/deactivate`, and `/listChats` working without Google Drive.
- The bot automatically creates and manages files in Google Drive - no manual setup required beyond sharing the folder.

## Deployment Options

### Android Phone (Recommended - Free & No IP Blocking)

Deploy on an Android phone using Termux for free hosting with a residential IP (avoids Instagram/YouTube blocking):

```bash
# Quick setup on Android/Termux
pkg install python nodejs ffmpeg git
git clone <your-repo-url>
cd telegram_group_insta_loader_bot
./install_on_termux.sh
```

See [QUICK_START_ANDROID.md](QUICK_START_ANDROID.md) for complete instructions.

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

- Python 3.9+ (Python 3.13 requires python-telegram-bot >= 21.0)
- python-telegram-bot >= 21.0 (for Python 3.13 compatibility)
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
