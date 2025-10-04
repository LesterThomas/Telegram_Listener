#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "flask",
#     "pyngrok",
# ]
# ///

import requests
import subprocess
import os
import sys
import atexit
import socket
from pathlib import Path
from flask import Flask, request, jsonify

# Parse command-line arguments
if len(sys.argv) != 6:
    print(
        "Usage: python telegram_claude_listener.py <BOT_TOKEN> <CHAT_ID> <MARKDOWN_FOLDER> <INSTANCE_ID> <NGROK_URL>"
    )
    print(
        "Example: python telegram_claude_listener.py 'your_bot_token' 'your_chat_id' 'C:\\path\\to\\markdown\\folder' 'bot1' 'https://abc123.ngrok.io'"
    )
    sys.exit(1)

# Configuration from command-line arguments
BOT_TOKEN = sys.argv[1]
CHAT_ID = sys.argv[2]
MARKDOWN_FOLDER = sys.argv[3]
INSTANCE_ID = sys.argv[4]
NGROK_URL = sys.argv[5].rstrip("/")  # Remove trailing slash if present
CLAUDE_CLI_PATH = "claude"  # Use just "claude" if it's in PATH, or try "claude.cmd"

# Telegram API endpoints
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
use_continue_flag = True  # Track whether to continue conversation or start fresh
last_session_date = None  # Track the date of the last session

# Flask app for webhook
app = Flask(__name__)


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
    global use_continue_flag, last_session_date

    try:
        # Change to your markdown folder
        os.chdir(MARKDOWN_FOLDER)

        # Add today's date to the message
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        message_with_date = f"{message}\n(Today's date is {today})"

        # Start a new session if it's a new day
        if last_session_date != today:
            use_continue_flag = False
            last_session_date = today
            print(f"🔄 New day detected ({today}), starting fresh session")

        print(f"Running Claude Code with message:\n{message_with_date}\n")

        # Build command with optional --continue flag
        cmd = ["cmd", "/c", CLAUDE_CLI_PATH, "--dangerously-skip-permissions"]
        if use_continue_flag:
            cmd.append("--continue")
        cmd.append(message_with_date)

        # Run Claude Code with the message, edit permissions, and optionally continue conversation
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # After first successful run, enable continue flag for subsequent messages
        if result.returncode == 0:
            use_continue_flag = True

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


def set_webhook(url):
    """Set the Telegram webhook"""
    webhook_url = f"{BASE_URL}/setWebhook"
    data = {"url": url, "allowed_updates": ["message"]}
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            print(f"✅ Webhook set successfully to: {url}")
            return True
        else:
            print(f"❌ Failed to set webhook: {result}")
            return False
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")
        return False


def delete_webhook():
    """Remove the Telegram webhook"""
    webhook_url = f"{BASE_URL}/deleteWebhook"
    try:
        response = requests.post(webhook_url)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            print("✅ Webhook deleted successfully")
            return True
        else:
            print(f"❌ Failed to delete webhook: {result}")
            return False
    except Exception as e:
        print(f"❌ Error deleting webhook: {e}")
        return False


def process_message(msg):
    """Process incoming Telegram message"""
    global use_continue_flag

    # Extract message details
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    # Only process messages from your chat
    if str(chat_id) != CHAT_ID:
        return

    # Handle commands
    if text.startswith("/"):
        if text == "/start":
            send_telegram_message(
                "🤖 Bot is running! Send me a message to update your markdown files via Claude Code."
            )
        elif text == "/newsession":
            use_continue_flag = False
            send_telegram_message(
                "🔄 Starting a new Claude Code session. Next message will begin a fresh conversation."
            )
        return

    # print(f"Received message: {text}")
    # send_telegram_message("⏳ Processing your request with Claude Code...")

    # Run Claude Code
    result = run_claude_code(text)
    if result:
        send_telegram_message(result)


@app.route(f"/webhook/<instance_id>", methods=["POST"])
def webhook(instance_id):
    """Handle incoming webhook from Telegram"""
    try:
        # Verify this is the correct instance
        if instance_id != INSTANCE_ID:
            return jsonify({"ok": False, "error": "Invalid instance ID"}), 404

        update = request.get_json()
        if update and "message" in update:
            process_message(update["message"])
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Error in webhook handler: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


def get_free_port():
    """Find and return a free port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def cleanup():
    """Cleanup function to remove webhook"""
    print("\n🧹 Cleaning up...")
    delete_webhook()


def main():
    """Main bot entry point with webhook"""
    # Register cleanup handler
    atexit.register(cleanup)

    print(f"🤖 Telegram bot started!")
    print(f"📂 Monitoring folder: {MARKDOWN_FOLDER}")
    print(f"💬 Listening for messages from chat ID: {CHAT_ID}")
    print(f"🆔 Instance ID: {INSTANCE_ID}")
    print("Press Ctrl+C to stop\n")

    try:
        # Use static port 5000
        port = 5000
        print(f"📡 Using port: {port}")

        # Set webhook using the provided ngrok URL
        webhook_url = f"{NGROK_URL}/webhook/{INSTANCE_ID}"
        print(f"🌐 Setting webhook to: {webhook_url}")
        if not set_webhook(webhook_url):
            print("❌ Failed to set webhook. Exiting.")
            return

        # Send startup notification
        # send_telegram_message("🚀 Claude Code bot is now running!")

        # Run Flask app
        print("🚀 Starting Flask webhook server...")
        print("Press Ctrl+C to stop\n")
        app.run(port=port, debug=False, use_reloader=False)

    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
        # send_telegram_message("🛑 Bot has been stopped")
    except Exception as e:
        print(f"❌ Error in main: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
