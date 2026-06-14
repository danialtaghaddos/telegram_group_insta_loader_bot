#!/bin/bash

# Debian/Proxmox LXC Installation Script for Telegram Instagram Loader Bot

echo "=========================================="
echo "Telegram Instagram Loader Bot Installer"
echo "  (Proxmox LXC / Debian)"
echo "=========================================="
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error()   { echo -e "${RED}✗ $1${NC}"; }
print_info()    { echo -e "${YELLOW}→ $1${NC}"; }

# Check root
if [ "$EUID" -ne 0 ]; then
    print_error "This script must be run as root (typical for Proxmox LXC)"
    print_info "Try: sudo ./install_on_debian.sh"
    exit 1
fi

# Check Debian/Ubuntu
if [ ! -f /etc/debian_version ]; then
    print_error "This script is intended for Debian/Ubuntu systems"
    exit 1
fi

# Check if running from the bot directory
if [ ! -f "requirements.txt" ]; then
    print_error "Please run this script from the bot directory"
    print_info "Example: cd /opt/telegram_group_insta_loader_bot && ./install_on_debian.sh"
    exit 1
fi

BOT_DIR="$(pwd)"
SERVICE_NAME="telegram-bot"

print_info "Bot directory: $BOT_DIR"
echo ""

# Step 1: Install system packages
print_info "Updating package lists..."
apt-get update -y

print_info "Installing system packages (python3, ffmpeg, nodejs, npm, yt-dlp, gallery-dl)..."
apt-get install -y python3 python3-venv python3-pip nodejs npm ffmpeg git curl wget yt-dlp gallery-dl

if [ $? -eq 0 ]; then
    print_success "System packages installed"
else
    print_error "Failed to install system packages"
    exit 1
fi

echo ""

# Step 2: Check Python version
print_info "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
print_success "Python $PYTHON_VERSION detected"

PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

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

python3 -m venv venv

if [ $? -eq 0 ]; then
    print_success "Virtual environment created"
else
    print_error "Failed to create virtual environment"
    exit 1
fi

echo ""

# Step 4: Install Python dependencies
print_info "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
INSTALL_STATUS=$?
deactivate

if [ $INSTALL_STATUS -eq 0 ]; then
    print_success "Python dependencies installed"
else
    print_error "Failed to install Python dependencies"
    exit 1
fi

echo ""

# Step 5: Create directories
print_info "Creating directories..."
mkdir -p data cookies logs
print_success "Directories created (data/, cookies/, logs/)"

echo ""

# Step 6: Set up .env file
if [ ! -f ".env" ]; then
    print_info "Creating .env file template..."
    cat > .env << 'EOF'
# Telegram Bot Configuration
# Get your bot token from @BotFather on Telegram
BOT_TOKEN=your_bot_token_here

# Your numeric Telegram user ID (get it from @userinfobot)
ADMIN_USER_ID=your_user_id

# Telethon credentials (optional — for username→ID resolution)
# Register your app at https://my.telegram.org/apps
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_STRING=

# Cookie files in Netscape format (optional — paths inside this directory)
# Example: COOKIES_TXT=cookies/instagram.txt
COOKIES_TXT=
FACEBOOK_COOKIES_TXT=
YOUTUBE_COOKIES_TXT=

# YouTube audio format: mp3 or m4a (default: m4a)
YOUTUBE_AUDIO_FORMAT=m4a

# Uncomment to activate the bot in all chats (debug/testing only)
# DEBUG_BOT=true
EOF
    chmod 600 .env
    print_success ".env file created — edit it before starting the bot"
else
    print_info ".env file already exists, skipping"
fi

echo ""

# Step 7: Create systemd service
print_info "Creating systemd service..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Telegram Instagram Loader Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${BOT_DIR}
EnvironmentFile=${BOT_DIR}/.env
ExecStart=${BOT_DIR}/venv/bin/python -m bot.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

if [ $? -eq 0 ]; then
    print_success "Systemd service '${SERVICE_NAME}' created and enabled (auto-starts on boot)"
else
    print_error "Failed to register systemd service"
fi

echo ""

# Step 8: Create helper scripts
print_info "Creating helper scripts..."

cat > start_bot.sh << 'EOF'
#!/bin/bash
systemctl start telegram-bot
echo "Bot started."
echo "Logs: journalctl -u telegram-bot -f"
EOF

cat > stop_bot.sh << 'EOF'
#!/bin/bash
systemctl stop telegram-bot
echo "Bot stopped."
EOF

cat > restart_bot.sh << 'EOF'
#!/bin/bash
systemctl restart telegram-bot
echo "Bot restarted."
echo "Logs: journalctl -u telegram-bot -f"
EOF

cat > check_bot.sh << 'EOF'
#!/bin/bash
case "${1:-status}" in
    status)
        systemctl status telegram-bot
        ;;
    logs)
        journalctl -u telegram-bot -n 50 --no-pager
        ;;
    follow)
        journalctl -u telegram-bot -f
        ;;
    restart)
        systemctl restart telegram-bot
        echo "Bot restarted"
        ;;
    stop)
        systemctl stop telegram-bot
        echo "Bot stopped"
        ;;
    start)
        systemctl start telegram-bot
        echo "Bot started"
        ;;
    *)
        echo "Telegram Instagram Loader Bot — Monitor"
        echo ""
        echo "Usage: $0 {status|logs|follow|restart|stop|start}"
        echo ""
        echo "  status   Check if bot is running"
        echo "  logs     Show last 50 log lines"
        echo "  follow   Stream logs live (Ctrl+C to exit)"
        echo "  restart  Restart the bot"
        echo "  stop     Stop the bot"
        echo "  start    Start the bot"
        ;;
esac
EOF

chmod +x start_bot.sh stop_bot.sh restart_bot.sh check_bot.sh
print_success "Helper scripts created (start/stop/restart/check_bot.sh)"

echo ""

# Final instructions
echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
print_info "1. Edit your .env file with your bot credentials:"
echo "   nano .env"
echo "   (Set BOT_TOKEN and ADMIN_USER_ID at minimum)"
echo ""
print_info "2. (Optional) Place cookie files in the cookies/ directory:"
echo "   cookies/instagram.txt, cookies/youtube.txt, etc."
echo "   Then set the matching COOKIES_TXT paths in .env"
echo ""
print_info "3. Start the bot:"
echo "   ./start_bot.sh"
echo "   (or: systemctl start telegram-bot)"
echo ""
print_info "4. Check status and live logs:"
echo "   ./check_bot.sh status"
echo "   ./check_bot.sh follow"
echo ""
print_info "5. The bot will auto-start on reboot (systemd enabled)"
echo ""
print_success "You're all set!"
