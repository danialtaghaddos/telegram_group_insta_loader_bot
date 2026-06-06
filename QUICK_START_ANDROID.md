# Quick Start Guide: Deploy Bot on Android Phone

**Estimated time:** 15 minutes  
**Cost:** Free (using your phone + home WiFi)

## Why Android Phone?

✅ **No more 403 errors** - Residential IP instead of data center IP  
✅ **Completely free** - No hosting costs  
✅ **Easy setup** - Just follow these steps  
✅ **Automatic recovery** - Restarts on phone reboot  

## Step-by-Step Instructions

### 1. Install Termux (2 minutes)

**Important:** Install from F-Droid, NOT Play Store

1. Download F-Droid: [f-droid.org](https://f-droid.org)
2. Install F-Droid on your phone
3. Open F-Droid → Search "Termux" → Install

### 2. Initial Setup (3 minutes)

Open Termux and run:

```bash
# Grant storage access
termux-setup-storage

# Update packages
pkg update && pkg upgrade

# Install required packages
pkg install python nodejs ffmpeg git wget
```

### 3. Clone and Install Bot (5 minutes)

```bash
# Create directory
mkdir -p ~/telegram_bot
cd ~/telegram_bot

# Clone your repository
git clone https://github.com/danialtaghaddos/telegram_group_insta_loader_bot.git .

# Run installation script
chmod +x install_on_termux.sh
./install_on_termux.sh
```

### 4. Configure Bot (3 minutes)

Edit the `.env` file:

```bash
nano .env
```

**Required settings:**

```env
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_USER_ID=your_telegram_user_id
```

**Optional but recommended:**

```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
YOUTUBE_COOKIES_TXT=your_cookies  # Helps prevent 403 errors
```

Save and exit (Ctrl+X, Y, Enter)

### 5. Start the Bot (1 minute)

```bash
./start_bot.sh
```

**That's it!** Your bot is now running.

### 6. Set Up Auto-Start (Optional but Recommended)

So the bot restarts when your phone reboots:

1. Install **Termux:Boot** from F-Droid
2. Open Termux:Boot app
3. Enable "Run on boot"
4. Grant permissions

**Done!** The bot will auto-start on phone reboot.

### 7. Important: Disable Battery Optimization

Prevent Android from killing Termux:

1. Go to **Settings** → **Apps** → **Termux**
2. Tap **Battery**
3. Select **Unrestricted** or disable **Battery optimization**

## Checking Bot Status

```bash
# Check if running
./check_bot.sh

# View logs
./check_bot.sh logs

# Follow logs in real-time
./check_bot.sh follow

# Restart bot
./check_bot.sh restart
```

## Troubleshooting

### Bot won't start?

```bash
# Check Python version (should be 3.11.x)
python --version

# Reinstall dependencies
source venv/bin/activate
pip install -r requirements.txt

# Check logs
tail -n 50 logs/bot.log
```

### Still getting 403 errors?

Add cookies to `.env`:

```env
YOUTUBE_COOKIES_TXT=your_youtube_cookies_here
COOKIES_TXT=your_instagram_cookies_here
```

Get cookies using browser extension "Get cookies.txt LOCALLY"

### Phone keeps killing the bot?

1. Disable battery optimization for Termux (see step 7)
2. Keep Termux app open in background
3. Don't "clean" Termux from recent apps

## Storage Management

The bot caches downloaded videos. Check usage:

```bash
du -sh ~/telegram_bot/data/
```

Clean old files if needed:

```bash
find ~/telegram_bot/data/ -type f -mtime +7 -delete
```

## Updating the Bot

```bash
cd ~/telegram_bot
git pull
./check_bot.sh restart
```

## Summary

Your bot is now running 24/7 on your Android phone with:

- ✅ Residential IP (no blocking)
- ✅ Free hosting
- ✅ Auto-restart capability
- ✅ Full logging and monitoring

**Next steps:** Test the bot by sending an Instagram link in a Telegram chat where it's activated!

---

For detailed troubleshooting and advanced configuration, see `termux_setup.md`
