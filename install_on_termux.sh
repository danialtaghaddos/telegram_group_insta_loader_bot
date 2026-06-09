#!/data/data/com.termux/files/usr/bin/bash

# Termux Installation Script for Telegram Instagram Loader Bot
# This script sets up the bot environment on Android/Termux

echo "=========================================="
echo "Telegram Instagram Loader Bot Installer"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}→ $1${NC}"
}

# Check if running in Termux
if [ ! -d "/data/data/com.termux" ]; then
    print_error "This script must be run in Termux on Android"
    exit 1
fi

# Check if running from telegram_bot directory
if [ ! -f "requirements.txt" ]; then
    print_error "Please run this script from the telegram_bot directory"
    print_info "Example: cd ~/telegram_bot && ./install_on_termux.sh"
    exit 1
fi

print_info "Starting installation..."
echo ""

# Step 1: Update and install system packages
print_info "Installing system packages..."
pkg update -y && pkg upgrade -y
pkg install -y python nodejs ffmpeg wget git curl rust

if [ $? -eq 0 ]; then
    print_success "System packages installed"
else
    print_error "Failed to install system packages"
    exit 1
fi

# Step 1b: Install build dependencies for cryptography package
print_info "Installing build dependencies for Python packages..."
pkg install -y libffi clang llvm

if [ $? -eq 0 ]; then
    print_success "System packages installed"
else
    print_error "Failed to install system packages"
    exit 1
fi

# Step 1c: Set Android API level for Rust/maturin builds
print_info "Configuring Android API level for Rust builds..."
# Get Android API level from Termux (usually 24 or higher)
if [ -z "$ANDROID_API_LEVEL" ]; then
    # Try to detect from termux properties or use a sensible default
    API_LEVEL=$(getprop ro.build.version.sdk 2>/dev/null || echo "24")
    export ANDROID_API_LEVEL="$API_LEVEL"
    print_success "Set ANDROID_API_LEVEL=$API_LEVEL"
else
    print_success "ANDROID_API_LEVEL already set: $ANDROID_API_LEVEL"
fi

echo ""

# Step 2: Check Python version
print_info "Checking Python version..."
PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
print_success "Python $PYTHON_VERSION detected"

# Check if Python is 3.9 or higher
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    print_error "Python 3.9+ is required. Found: $PYTHON_VERSION"
    exit 1
fi

echo ""

# Step 3: Create virtual environment
print_info "Creating virtual environment..."
if [ -d "venv" ]; then
    print_info "Virtual environment already exists, removing..."
    rm -rf venv
fi

python -m venv venv

if [ $? -eq 0 ]; then
    print_success "Virtual environment created"
else
    print_error "Failed to create virtual environment"
    exit 1
fi

echo ""

# Step 4: Activate virtual environment and install dependencies
print_info "Installing Python dependencies..."
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ $? -eq 0 ]; then
    print_success "Python dependencies installed"
else
    print_error "Failed to install Python dependencies"
    exit 1
fi

echo ""

# Step 5: Create necessary directories
print_info "Creating directories..."
mkdir -p data
mkdir -p logs
mkdir -p ~/.termux/boot

print_success "Directories created"

echo ""

# Step 6: Set up .env file if it doesn't exist
if [ ! -f ".env" ]; then
    print_info "Creating .env file template..."
    cat > .env << 'EOF'
# Telegram Bot Configuration
# Get your bot token from @BotFather on Telegram
BOT_TOKEN=your_bot_token_here

# Telegram API Credentials (for Telethon client)
# Register your app at https://my.telegram.org/apps
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_STRING=

# Admin Configuration
# Your Telegram numeric user ID (can be obtained from @userinfobot)
ADMIN_USER_ID=your_user_id

# Cookie Configuration (optional)
# Cookies for general downloads (cookies.txt format)
COOKIES_TXT=

# Facebook-specific cookies (cookies.txt format)
FACEBOOK_COOKIES_TXT=

# YouTube-specific cookies (cookies.txt format) - helps prevent 403 errors
YOUTUBE_COOKIES_TXT=

# YouTube Download Configuration (optional)
# Audio format for YouTube downloads: mp3 or m4a
YOUTUBE_AUDIO_FORMAT=m4a

# Debug Mode (optional)
# Set to true to enable debug logging
DEBUG_BOT=false
EOF
    chmod 600 .env
    print_success ".env file created (please edit with your values)"
else
    print_info ".env file already exists"
fi

echo ""

# Step 7: Create start script
print_info "Creating start script..."
cat > start_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Start script for Telegram Instagram Loader Bot

cd ~/telegram_bot

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Run install_on_termux.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Create logs directory if it doesn't exist
mkdir -p logs

# Check if bot is already running
if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
    echo "Bot is already running!"
    echo "Use './check_bot.sh' to see status and logs"
    exit 0
fi

echo "Starting Telegram Instagram Loader Bot..."
echo "Logs: ~/telegram_bot/logs/bot.log"
echo "Press Ctrl+C to stop (or run in background with: ./start_bot.sh &)"
echo ""

# Start the bot
nohup python -m bot.main > logs/bot.log 2>&1 &

# Wait a moment and check if it started successfully
sleep 2
if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
    echo "✓ Bot started successfully!"
    echo "Process ID: $(ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}')"
else
    echo "✗ Failed to start bot. Check logs:"
    tail -n 20 logs/bot.log
    exit 1
fi
EOF

chmod +x start_bot.sh
print_success "Start script created"

echo ""

# Step 8: Create restart script
print_info "Creating restart script..."
cat > restart_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Restart script for Telegram Instagram Loader Bot

cd ~/telegram_bot

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Restarting Telegram Instagram Loader Bot...${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}Error: Virtual environment not found. Run install_on_termux.sh first.${NC}"
    exit 1
fi

# Stop the bot if running
if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
    echo "Stopping bot..."
    ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}' | xargs kill -9 2>/dev/null
    sleep 2
    echo -e "${GREEN}✓ Bot stopped${NC}"
else
    echo "Bot was not running"
fi

# Create logs directory if it doesn't exist
mkdir -p logs

# Start the bot
echo "Starting bot..."
source venv/bin/activate
nohup python -m bot.main > logs/bot.log 2>&1 &

# Wait a moment and check if it started successfully
sleep 3
if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
    PID=$(ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}')
    echo -e "${GREEN}✓ Bot restarted successfully!${NC}"
    echo "Process ID: $PID"
    echo "Logs: ~/telegram_bot/logs/bot.log"
else
    echo -e "${RED}✗ Failed to start bot. Check logs:${NC}"
    tail -n 20 logs/bot.log
    exit 1
fi
EOF

chmod +x restart_bot.sh
print_success "Restart script created"

echo ""

# Step 9: Create monitoring script
print_info "Creating monitoring script..."
cat > check_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Monitoring script for Telegram Instagram Loader Bot

cd ~/telegram_bot

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to check if bot is running
check_status() {
    if ps aux | grep -v grep | grep "python -m bot.main" > /dev/null; then
        PID=$(ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}')
        echo -e "${GREEN}✓ Bot is RUNNING${NC}"
        echo "  Process ID: $PID"
        
        # Show uptime
        UPTIME=$(ps -o etimes= -p $PID 2>/dev/null | tr -d ' ')
        if [ ! -z "$UPTIME" ]; then
            HOURS=$((UPTIME / 3600))
            MINUTES=$(((UPTIME % 3600) / 60))
            SECONDS=$((UPTIME % 60))
            echo "  Uptime: ${HOURS}h ${MINUTES}m ${SECONDS}s"
        fi
        
        # Show recent log entries
        echo ""
        echo "Recent logs:"
        tail -n 10 logs/bot.log 2>/dev/null || echo "  No logs found"
        
        return 0
    else
        echo -e "${RED}✗ Bot is NOT RUNNING${NC}"
        return 1
    fi
}

# Main menu
case "${1:-status}" in
    status)
        check_status
        ;;
    logs)
        echo "Showing last 50 lines of log:"
        tail -n 50 logs/bot.log
        ;;
    follow)
        echo "Following logs (Ctrl+C to stop):"
        tail -f logs/bot.log
        ;;
    restart)
        echo "Stopping bot..."
        ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}' | xargs kill -9 2>/dev/null
        sleep 1
        echo "Starting bot..."
        ./start_bot.sh
        ;;
    stop)
        echo "Stopping bot..."
        ps aux | grep -v grep | grep "python -m bot.main" | awk '{print $2}' | xargs kill -9 2>/dev/null
        echo "Bot stopped"
        ;;
    start)
        ./start_bot.sh
        ;;
    *)
        echo "Telegram Instagram Loader Bot - Monitor Script"
        echo ""
        echo "Usage: $0 {status|logs|follow|restart|stop|start}"
        echo ""
        echo "Commands:"
        echo "  status   - Check if bot is running and show recent logs"
        echo "  logs     - Show last 50 lines of log"
        echo "  follow   - Follow log file in real-time"
        echo "  restart  - Stop and start the bot"
        echo "  stop     - Stop the bot"
        echo "  start    - Start the bot"
        ;;
esac
EOF

chmod +x check_bot.sh
print_success "Monitoring script created"

echo ""

# Step 10: Create auto-start script for Termux:Boot
print_info "Setting up auto-start..."
cat > ~/.termux/boot/start-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Auto-start script for Telegram Instagram Loader Bot
# This runs when the phone boots up (requires Termux:Boot app)

# Wait for network to be ready
print_info "Waiting for network..."
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
EOF

chmod +x ~/.termux/boot/start-bot.sh
print_success "Auto-start script created"

echo ""

# Step 11: Final instructions
echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
print_info "1. Configure your .env file:"
echo "   nano .env"
echo "   (Set BOT_TOKEN, ADMIN_USER_ID, and optionally cookies)"
echo ""
print_info "2. Start the bot:"
echo "   ./start_bot.sh"
echo ""
print_info "3. Restart the bot:"
echo "   ./restart_bot.sh"
echo ""
print_info "4. Check bot status:"
echo "   ./check_bot.sh"
echo ""
print_info "5. Set up auto-start (optional):"
echo "   - Install Termux:Boot from F-Droid"
echo "   - Open Termux:Boot app and enable 'Run on boot'"
echo ""
print_info "6. Important: Disable battery optimization for Termux"
echo "   - Go to Phone Settings → Apps → Termux"
echo "   - Disable 'Battery optimization'"
echo ""
echo "For detailed instructions, see: termux_setup.md"
echo ""
print_success "You're all set!"