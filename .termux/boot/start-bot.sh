#!/data/data/com.termux/files/usr/bin/bash

# Auto-start script for Telegram Instagram Loader Bot
# This runs when the phone boots up (requires Termux:Boot app)

# Wait for network to be ready
sleep 30

# Check if network is available
if ! ping -c 1 8.8.8.8 > /dev/null 2>&1; then
    echo "Network not available, waiting longer..."
    sleep 30
fi

# Navigate to bot directory
cd ~/telegram_bot

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "$(date): Virtual environment not found, skipping auto-start" >> logs/boot.log
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Create logs directory if needed
mkdir -p logs

# Start the bot
nohup python -m bot.main > logs/bot.log 2>&1 &

# Log the startup
echo "$(date): Bot auto-started (PID: $!)" >> logs/boot.log

# Wait and verify
sleep 5
if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
    echo "$(date): Bot started successfully" >> logs/boot.log
else
    echo "$(date): Bot failed to start" >> logs/boot.log
fi