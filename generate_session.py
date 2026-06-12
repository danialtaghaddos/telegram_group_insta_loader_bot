#!/usr/bin/env python3
"""
Telethon Session Generator

This script helps you generate a session string for the Telegram user account.
The session string allows the bot to upload large files (up to 2GB/4GB) via your user account.

Usage:
    python generate_session.py

Requirements:
    - TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env.local
    - You must have a Telegram account
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env.local
load_dotenv(Path(__file__).parent / ".env.local")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

if not API_ID or not API_HASH:
    print("❌ Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env.local")
    print("   Get them from: https://my.telegram.org/apps")
    sys.exit(1)

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("🔐 Telethon Session Generator")
print("=" * 50)
print()
print("This script will create a session for your Telegram user account.")
print("The session allows the bot to upload large files via your account.")
print()
print("📱 You will receive a login code via Telegram.")
print()

# Create a new session
session_name = "bot_user_session"

with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
    # The client will automatically prompt for phone number and login code
    print()
    print("✅ Session created successfully!")
    print()
    
    # Get the session string
    session_string = client.session.save()
    
    print("=" * 50)
    print("📋 Copy this session string to your .env.local file:")
    print()
    print(f"TELEGRAM_SESSION_STRING={session_string}")
    print()
    print("=" * 50)
    print()
    print("After adding this to .env.local, restart your bot.")
    print()
    
    # Also print user info
    me = client.get_me()
    print(f"👤 Logged in as: {me.first_name} (@{me.username or 'no_username'})")
    print(f"   User ID: {me.id}")