# Telegram Group Instagram Loader Bot

A Telegram bot that downloads and shares Instagram, Facebook, and YouTube media in group chats. Features a moderator system allowing multiple users to manage bot activation per chat.

## Project Structure

```
telegram_group_insta_loader_bot/
├── bot/
│   ├── main.py               # Entry point, command/message handler registration
│   ├── config.py             # Environment variable loading
│   ├── handlers.py           # Message handlers for social media links
│   ├── downloaders.py        # Media download logic (yt-dlp, gallery-dl)
│   ├── worker.py             # Background worker (3 concurrent) for download queue
│   ├── activation.py         # Chat activation/deactivation and doorman mode
│   ├── moderators.py         # Moderator management and access requests
│   ├── telethon_client.py    # Telethon client for username resolution
│   ├── utils.py              # Utility functions
│   └── video.py              # Video compression and metadata
├── data/                     # JSON file persistence
│   ├── activated_chats.json
│   ├── doorman_chats.json
│   ├── moderators.json       # Format: {user_id: []}
│   ├── access_requests.json
│   ├── activation_requests.json
│   └── settings.json
├── .env.local                # Local environment variables (not committed)
├── requirements.txt
└── Dockerfile
```

## Architecture

- **python-telegram-bot 21.x** for the Bot API layer
- **asyncio.Queue** (max 30 items) with 3 concurrent worker tasks for download processing
- **yt-dlp** + **gallery-dl** for media downloading; **FFmpeg** for compression
- **Telethon** (optional) for resolving usernames to user IDs without prior bot interaction
- All state persisted in JSON files under `data/`

### Handler Registration Order (matters)

In `main.py`: callbacks → doorman → protected message handlers

### Download Flow

1. `handlers.py` extracts URLs. In group chats they're queued immediately via `asyncio.Queue`. In private chats (moderators/admin only — see User Roles), each URL first gets an inline quality picker: YouTube offers Audio vs. Video, then a format/tier keyboard; other platforms go straight to a High/Medium/Low quality picker. Pending picker state lives in `handlers.PENDING_QUALITY`, keyed by a short request id embedded in the callback data (`q:<rid>:<step>:<value>`).
2. `worker.py` dequeues `(update, context, url, status_msg, reply_id, message, task_id, quality)` — `quality` is `None`/`{}` for group chats (legacy defaults) or a dict (`kind`, `tier`, `height_cap`/`audio_format`/`audio_bitrate`) for private-chat picks — calls `downloaders.py`, and compresses video with FFmpeg (`video.compress_video`, tier-aware) if needed.
3. Uploads to chat. Instagram captions (fetched via yt-dlp metadata) are attached to the first media item and truncated to 1000 chars in group chats; in private chats the caption is sent as a separate follow-up message instead, untruncated.
4. Files over Telegram's 50MB bot upload limit are forwarded via the admin's Telethon account into the admin's chat, then copied into the target chat (see `telethon_client.upload_to_admin_chat` + `main.handle_admin_forwarded_file`). In private chats this includes live upload-progress edits on the status message; any pending follow-up caption is stashed in `config.large_file_captions` and delivered once the copy completes.

## Key Configuration

Required env vars:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `ADMIN_USER_ID` | Admin's numeric Telegram user ID |

Optional env vars:

| Variable | Description |
|----------|-------------|
| `DEBUG_BOT` | Activate bot in all chats (debug mode) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION_STRING` | Telethon credentials |
| `YOUTUBE_AUDIO_FORMAT` | `mp3` or `m4a` (default: `m4a`) |
| `COOKIES_TXT` | Instagram cookies (Netscape format) |
| `FACEBOOK_COOKIES_TXT` | Facebook cookies (Netscape format) |
| `YOUTUBE_COOKIES_TXT` | YouTube cookies (Netscape format) |

## User Roles

| Role | Permissions |
|------|-------------|
| **Admin** | Full access; defined by `ADMIN_USER_ID` |
| **Moderator** | Can activate/deactivate bot and doorman mode in any chat they belong to |
| **Regular user** | Can send links in activated chats; can request moderator access |

## Commands

### Public
- `/access` — Request moderator access
- `/help` — Context-aware help (varies by role)

### Moderator
- `/activate` / `/deactivate` — Toggle bot for current chat
- `/doorman` — Toggle auto-delete of join/leave messages
- `/myChats` — Check moderator status

### Admin only
- `/listChats` — All activated chats
- `/listMods` — All moderators
- `/approve <user_id>` / `/deny <user_id>` — Handle moderator access requests
- `/requests` — View pending access requests
- `/addMods @username` / `/removemod @username` — Direct moderator management
- `/load` — Reply to a message containing links to force-download
- `/activation_requests` — View pending chat activation requests
- `/approve_activation <chat_id>` / `/deny_activation <chat_id>` — Handle activation requests
