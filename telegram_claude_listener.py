#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
# ]
# ///

import requests
import time
import subprocess
import os
import sys
from pathlib import Path

# Parse command-line arguments
if len(sys.argv) != 4:
    print(
        "Usage: python telegram_claude_listener.py <BOT_TOKEN> <CHAT_ID> <MARKDOWN_FOLDER>"
    )
    print(
        "Example: python telegram_claude_listener.py 'your_bot_token' 'your_chat_id' 'C:\\path\\to\\markdown\\folder'"
    )
    sys.exit(1)

# Configuration from command-line arguments
BOT_TOKEN = sys.argv[1]
CHAT_ID = sys.argv[2]
MARKDOWN_FOLDER = sys.argv[3]
CLAUDE_CLI_PATH = "claude"  # Use just "claude" if it's in PATH, or try "claude.cmd"
POLL_INTERVAL = 10  # seconds

# Telegram API endpoints
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = None


def convert_markdown_to_html(text):
    """Convert common markdown patterns to HTML for Telegram"""
    import re

    # Convert markdown to HTML
    # Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<i>\1</i>", text)

    # Code: `text` -> <code>text</code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Code blocks: ```text``` -> <pre>text</pre>
    text = re.sub(r"```([^`]+)```", r"<pre>\1</pre>", text)

    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Obsidian links: [[link]] -> <u>link</u> (underline to show they were links)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"<u>\1</u>", text)

    return text


def send_telegram_message(text, parse_mode="auto"):
    """Send a message back to Telegram with markdown formatting"""
    url = f"{BASE_URL}/sendMessage"

    # Try different formatting approaches
    attempts = []

    if parse_mode == "auto":
        # First try: HTML with markdown conversion (most reliable)
        attempts.append(("HTML", convert_markdown_to_html(text)))
        # Second try: Legacy Markdown (simpler escaping)
        attempts.append(("Markdown", text))
        # Third try: MarkdownV2 as-is (risky but might work)
        attempts.append(("MarkdownV2", text))
        # Last resort: Plain text
        attempts.append((None, text))
    else:
        attempts.append((parse_mode, text))

    for attempt_parse_mode, attempt_text in attempts:
        data = {"chat_id": CHAT_ID, "text": attempt_text}
        if attempt_parse_mode:
            data["parse_mode"] = attempt_parse_mode

        try:
            print(f"Trying to send message with {attempt_parse_mode or 'plain text'}")
            print(f"Message content:\n{attempt_text}\n")
            response = requests.post(url, data=data)
            if response.ok:
                print("Message sent successfully")
                return  # Success, exit
            else:
                print(
                    f"Failed with {attempt_parse_mode or 'plain text'}: {response.text}"
                )
        except Exception as e:
            print(f"Error with {attempt_parse_mode or 'plain text'}: {e}")

    print("All formatting attempts failed")


def run_claude_code(message):
    """Send the message to Claude Code"""
    try:
        # Change to your markdown folder
        os.chdir(MARKDOWN_FOLDER)

        print(f"Running Claude Code with message:\n{message}\n")
        # Run Claude Code with the message and edit permissions
        result = subprocess.run(
            ["cmd", "/c", CLAUDE_CLI_PATH, "--dangerously-skip-permissions", message],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            print(
                f"❌ Claude Code failed with exit code {result.returncode}\n\nError:\n{result.stderr}\n\nOutput:\n{result.stdout}"
            )
            return None
        print(f"✅ Claude Code completed successfully.\n\nOutput:\n{result.stdout}")
        return result.stdout

    except FileNotFoundError:
        print(
            "❌ Claude CLI not found. Please check if Claude is installed and accessible from PATH, or update CLAUDE_CLI_PATH in the script."
        )
        return None
    except subprocess.TimeoutExpired:
        print("⏱️ Claude Code timed out (took longer than 5 minutes)")
        return None
    except Exception as e:
        print(f"Error running Claude Code: {e}")
        return None


def get_updates():
    """Poll Telegram for new messages"""
    global last_update_id

    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 30, "allowed_updates": ["message"]}

    if last_update_id:
        params["offset"] = last_update_id + 1

    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        print(f"Error getting updates: {e}")
        return None


def process_message(message):
    """Process incoming Telegram message"""
    global last_update_id

    update_id = message.get("update_id")
    last_update_id = update_id

    # Extract message details
    msg = message.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    # Only process messages from your chat
    if str(chat_id) != CHAT_ID:
        return

    # Skip commands like /start
    if text.startswith("/"):
        if text == "/start":
            send_telegram_message(
                "🤖 Bot is running! Send me a message to update your markdown files via Claude Code."
            )
        return

    # print(f"Received message: {text}")
    # send_telegram_message("⏳ Processing your request with Claude Code...")

    # Run Claude Code
    result = run_claude_code(text)
    if result:
        send_telegram_message(result)


def main():
    """Main bot loop"""
    print(f"🤖 Telegram bot started!")
    print(f"📂 Monitoring folder: {MARKDOWN_FOLDER}")
    print(f"💬 Listening for messages from chat ID: {CHAT_ID}")
    print("Press Ctrl+C to stop\n")

    # Send startup notification
    # send_telegram_message("🚀 Claude Code bot is now running!")

    while True:
        try:
            updates = get_updates()

            if updates and updates.get("ok"):
                for update in updates.get("result", []):
                    process_message(update)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n👋 Bot stopped")
            # send_telegram_message("🛑 Bot has been stopped")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
