# Complete Termux Deployment Guide for Telegram Instagram Loader Bot

This guide will help you deploy your Telegram bot on an Android phone using Termux. The bot will run 24/7 on your home WiFi, avoiding the IP blocking issues you experienced with Railway.

## Prerequisites

- Android phone with WiFi capability
- Stable home WiFi connection
- At least 2GB free storage on phone
- Termux installed from F-Droid (NOT from Play Store)

## Table of Contents

1. [Initial Termux Setup](#initial-termux-setup)
2. [One-Command Installation](#one-command-installation)
3. [Configuration](#configuration)
4. [Running the Bot](#running-the-bot)
5. [Auto-Start on Phone Boot](#auto-start-on-phone-boot)
6. [Monitoring and Maintenance](#monitoring-and-maintenance)
7. [Troubleshooting](#troubleshooting)

## Initial Termux Setup

### Step 1: Install Termux from F-Droid

1. Download F-Droid from [f-droid.org](https://f-droid.org)
2. Install F-Droid on your phone
3. Open F-Droid and search for "Termux"
4. Install Termux

### Step 2: Initial Configuration

Open Termux and run these commands:

```bash
# Grant storage access
termux-setup-storage

# Update packages
pkg update && pkg upgrade

# Install required packages (including Rust for cryptography build)
pkg install python nodejs ffmpeg wget git curl rust libffi clang llvm
```

### Step 3: Verify Python Version

```bash
python --version
```

You should see Python 3.11.x (this is perfect - compatible with your bot).

## One-Command Installation

### Option A: Automated Installation (Recommended)

Copy and paste this entire block into Termux:

```bash
# Create project directory
mkdir -p ~/telegram_bot
cd ~/telegram_bot

# Clone your repository (replace with your actual repo URL)
git clone https://github.com/danialtaghaddos/telegram_group_insta_loader_bot.git .

# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create necessary directories
mkdir -p data
mkdir -p logs

# Set up auto-start directory
mkdir -p ~/.termux/boot

echo "Installation complete!"
```

### Option B: Using the Installation Script

I've created an installation script for you. After cloning your repository:

```bash
cd ~/telegram_bot
chmod +x install_on_termux.sh
./install_on_termux.sh
```

## Configuration

### Step 1: Set Up Environment Variables

Copy your `.env` file to the bot directory:

```bash
# Method 1: If you have .env on your phone's storage
cp /sdcard/Download/.env ~/telegram_bot/.env

# Method 2: Create .env manually
nano ~/telegram_bot/.env
```

### Step 2: Edit .env File

Make sure your `.env` file contains:

```env
# Required
BOT_TOKEN=your_bot_token_here
ADMIN_USER_ID=your_telegram_user_id

# Optional but recommended
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# YouTube cookies (helps prevent 403 errors)
YOUTUBE_COOKIES_TXT=your_youtube_cookies_here

# Cache configuration
CACHE_DIR=/data/data/com.termux/files/home/telegram_bot/data/tg_media_cache
CACHE_TTL_HOURS=24
CACHE_CLEANUP_INTERVAL_MINUTES=60

# Set to false for production
DEBUG_BOT=false
```

### Step 3: Set Proper Permissions

```bash
chmod 600 ~/telegram_bot/.env
```

## Running the Bot

### Manual Start

```bash
# Navigate to bot directory
cd ~/telegram_bot

# Activate virtual environment
source venv/bin/activate

# Start the bot
python -m bot.main
```

### Running in Background

```bash
# Using nohup (persists after closing Termux)
cd ~/telegram_bot
source venv/bin/activate
nohup python -m bot.main > logs/bot.log 2>&1 &

# Check if bot is running
ps aux | grep "python -m bot.main"
```

### Restart the Bot

```bash
# Using the restart script (recommended)
cd ~/telegram_bot
./restart_bot.sh

# Or use the check_bot.sh script
./check_bot.sh restart
```

### Stop the Bot

```bash
# Using the check_bot.sh script
./check_bot.sh stop

# Or manually find and kill the process
ps aux | grep "python -m bot.main"
kill PID
```

## Auto-Start on Phone Boot

### Step 1: Install Termux:Boot

1. Open F-Droid
2. Search for "Termux:Boot"
3. Install Termux:Boot

### Step 2: Create Boot Script

```bash
# Create boot script
nano ~/.termux/boot/start-bot.sh
```

Add this content:

```bash
#!/data/data/com.termux/files/usr/bin/bash

# Wait for network to be ready
sleep 30

# Activate virtual environment and start bot
cd ~/telegram_bot
source venv/bin/activate

# Start bot in background with logging
nohup python -m bot.main > ~/telegram_bot/logs/bot.log 2>&1 &

echo "Bot started at $(date)" >> ~/telegram_bot/logs/boot.log
```

### Step 3: Make Script Executable

```bash
chmod +x ~/.termux/boot/start-bot.sh
```

### Step 4: Enable Termux:Boot

1. Open Termux:Boot app
2. Enable "Run on boot"
3. Grant necessary permissions

## Monitoring and Maintenance

### Check Bot Status

```bash
# Using the monitoring script
cd ~/telegram_bot
chmod +x check_bot.sh
./check_bot.sh
```

### View Logs

```bash
# View recent logs
tail -f ~/telegram_bot/logs/bot.log

# View last 50 lines
tail -n 50 ~/telegram_bot/logs/bot.log
```

### Update Bot

```bash
cd ~/telegram_bot
git pull
source venv/bin/activate
pip install -r requirements.txt

# Restart the bot using the dedicated script
./restart_bot.sh
```

### Storage Management

```bash
# Check storage usage
du -sh ~/telegram_bot/data/

# Clean up old cached files (older than 24 hours)
find ~/telegram_bot/data/ -type f -mtime +1 -delete
```

## Troubleshooting

### Issue: Bot won't start

**Solution:**

```bash
# Check Python version
python --version

# Reinstall dependencies
source venv/bin/activate
pip install -r requirements.txt --force-reinstall

# Check logs
tail -n 100 ~/telegram_bot/logs/bot.log
```

### Issue: 403 errors from Instagram/YouTube

**Solutions:**

1. Add cookies to `.env`:

   ```env
   YOUTUBE_COOKIES_TXT=your_cookies_here
   COOKIES_TXT=your_cookies_here
   ```

2. Wait a few hours (temporary rate limiting)
3. Check if your home IP is blocked (try accessing Instagram from phone browser)

### Issue: Bot stops after phone sleep

**Solution:**

1. Go to Phone Settings → Apps → Termux
2. Disable "Battery optimization" for Termux
3. Allow "Run in background" permission

### Issue: WiFi disconnects

**Solution:**

```bash
# Create a WiFi lock script
cat > ~/telegram_bot/wifi_lock.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
while true; do
    ping -c 1 8.8.8.8 > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "WiFi disconnected, waiting..." >> ~/telegram_bot/logs/wifi.log
        sleep 30
    fi
done
EOF

chmod +x ~/telegram_bot/wifi_lock.sh
nohup ~/telegram_bot/wifi_lock.sh > /dev/null 2>&1 &
```

### Issue: Storage full

**Solution:**

```bash
# Reduce cache TTL in .env
CACHE_TTL_HOURS=12

# Manually clean cache
rm -rf ~/telegram_bot/data/tg_media_cache/*

# Set up automatic cleanup
crontab -e
# Add this line to run cleanup every 6 hours:
0 */6 * * * find ~/telegram_bot/data/tg_media_cache -type f -mtime +1 -delete
```

### Issue: Python version problems

If you encounter Python version issues:

```bash
# Remove virtual environment
rm -rf ~/telegram_bot/venv

# Create new one
python -m venv venv

# Activate and reinstall
source venv/bin/activate
pip install -r requirements.txt
```

### Issue: "Failed to build 'cryptography'" or "Rust not found"

This error occurs when building the `cryptography` package, which requires Rust as a build dependency.

**Solution:**

Install Rust and other build dependencies:

```bash
pkg install rust libffi clang llvm
```

Then retry installing Python dependencies:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

If you've already created a virtual environment before installing Rust, you may need to recreate it:

```bash
# Remove old virtual environment
rm -rf ~/telegram_bot/venv

# Create new one
python -m venv venv

# Activate and reinstall
source venv/bin/activate
pip install -r requirements.txt
```

### Issue: "maturin failed" or "Failed to determine Android API level"

This error occurs when building Rust-based Python packages (like `cryptography`) on Termux. The maturin build tool needs the Android API level to be set.

**Solution:**

Set the `ANDROID_API_LEVEL` environment variable and retry:

```bash
# Set Android API level (usually 24 or higher)
export ANDROID_API_LEVEL=24

# Or auto-detect from your device
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)

# Then retry installing
source venv/bin/activate
pip install -r requirements.txt
```

If the above doesn't work, you may need to recreate the virtual environment after setting the environment variable:

```bash
# Set the environment variable
export ANDROID_API_LEVEL=24

# Remove and recreate virtual environment
rm -rf ~/telegram_bot/venv
python -m venv venv

# Activate and install
source venv/bin/activate
pip install -r requirements.txt
```

## Performance Tips

1. **Limit concurrent downloads**: The bot already has a queue system (max 30 items)
2. **Monitor storage**: Check `du -sh ~/telegram_bot/data/` weekly
3. **Update regularly**: Run `git pull` monthly for bug fixes
4. **Backup data**: Periodically copy `~/telegram_bot/data/` to cloud storage

## Getting Help

If you encounter issues:

1. Check logs: `tail -f ~/telegram_bot/logs/bot.log`
2. Verify configuration: `cat ~/telegram_bot/.env`
3. Test Instagram access from phone browser
4. Restart the bot: `./restart_bot.sh`

## Summary

Your bot is now running on your Android phone with:

- ✅ Residential IP (no more 403 errors)
- ✅ Free hosting (your phone + WiFi)
- ✅ Auto-restart on phone reboot
- ✅ Logging and monitoring
- ✅ Storage management

The bot will continue running as long as your phone has power and WiFi connectivity.
