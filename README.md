# Telegram Group Instagram Loader Bot

A Telegram bot that downloads and shares Instagram/Facebook media in Telegram chats. The bot supports a moderator system allowing multiple users to manage bot activation in their own chats.

## Features

- 📸 **Download Instagram/Facebook Media** - Simply send Instagram or Facebook links in an activated chat to download and share media
- 👥 **Moderator System** - Multiple moderators can manage bot activation in their respective chats
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

Moderators can activate/deactivate the bot and manage doorman settings **only in chats they control**.

| Command | Description |
|---------|-------------|
| `/activate` | Activate the bot for the current chat (moderators can only activate chats they control) |
| `/deactivate` | Deactivate the bot for the current chat (moderators can only deactivate chats they control) |
| `/doorman` | Toggle doorman mode - auto-deletes join/leave system messages |
| `/myChats` | List all chats you are a moderator of |
| `/help` | Show all available commands |

### For Admin Only

| Command | Description |
|---------|-------------|
| `/listChats` | List all activated chats across the bot |
| `/approve <user_id>` | Approve a pending moderator access request. Reply to the request notification or provide user ID |
| `/deny <user_id>` | Deny a pending moderator access request. Reply to the request notification or provide user ID |
| `/requests` | View all pending moderator access requests |
| `/enable` | Enable access requests - allows users to use `/access` to request moderator access |
| `/disable` | Disable access requests - users cannot request moderator access |
| `/addmod @username [chat_id]` | Manually add a user as moderator. If chat_id is not provided, current chat is used |
| `/removemod @username [chat_id]` | Remove a user as moderator. If chat_id is not provided and used in a group, removes from that group. If used in private chat, removes all roles |
| `/activate` | Activate the bot for the current chat (admin has access to all chats) |
| `/deactivate` | Deactivate the bot for the current chat (admin has access to all chats) |
| `/doorman` | Toggle doorman mode (admin has access to all chats) |

## How It Works

### Moderator Access Flow

1. **Request Access**: Users run `/access` to request moderator privileges (if enabled by admin)
2. **Admin Notification**: The admin receives a notification with the user's details
3. **Approval/Denial**: Admin uses `/approve` or `/deny` to respond to the request
4. **Moderator Permissions**: Once approved, the new moderator can manage the bot in the chat where they were approved

### Manual Moderator Addition

Admin can directly add moderators using:
```
/addmod @username [chat_id]
```

### Chat Activation

- **Admin**: Can activate/deactivate the bot in any chat
- **Moderators**: Can only activate/deactivate chats they are assigned to
- Once activated, users in that chat can send Instagram/Facebook links to download media

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `ADMIN_USER_ID` | Your Telegram numeric user ID (the bot admin) |
| `DEBUG_BOT` | Set to enable debug mode (optional) |

### Data Storage

The bot stores data in JSON files in the `/data` directory:

- `activated_chats.json` - List of chat IDs where the bot is activated
- `doorman_chats.json` - List of chat IDs with doorman mode enabled
- `moderators.json` - Moderator assignments (user_id -> chat_ids)
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

## License

MIT License