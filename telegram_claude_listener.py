#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "flask",
#     "python-dotenv",
# ]
# ///

import requests
import subprocess
import os
import sys
import atexit
from pathlib import Path
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Flask app for webhook
app = Flask(__name__)

# Store bot instances configuration
bot_instances = {}
# Track conversation state for each bot instance
bot_states = {}


def load_bot_instances():
    """Load bot instances from environment variables"""
    instances = {}
    i = 1
    while True:
        prefix = f"BOT{i}_"
        token = os.getenv(f"{prefix}TOKEN")
        chat_id = os.getenv(f"{prefix}CHAT_ID")
        markdown_folder = os.getenv(f"{prefix}MARKDOWN_FOLDER")
        instance_id = os.getenv(f"{prefix}INSTANCE_ID")

        if not all([token, chat_id, markdown_folder, instance_id]):
            break

        instances[instance_id] = {
            "token": token,
            "chat_id": chat_id,
            "markdown_folder": markdown_folder,
            "instance_id": instance_id,
            "base_url": f"https://api.telegram.org/bot{token}",
        }

        # Initialize state for this bot
        bot_states[instance_id] = {
            "use_continue_flag": True,
            "last_session_date": None,
        }

        i += 1

    return instances


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


def send_telegram_message(instance_id, text, parse_mode="auto"):
    """Send a message back to Telegram with markdown formatting"""
    bot_config = bot_instances[instance_id]
    url = f"{bot_config['base_url']}/sendMessage"

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
        data = {"chat_id": bot_config["chat_id"], "text": attempt_text}
        if attempt_parse_mode:
            data["parse_mode"] = attempt_parse_mode

        try:
            print(
                f"[{instance_id}] Trying to send message with {attempt_parse_mode or 'plain text'}"
            )
            print(f"Message content:\n{attempt_text}\n")
            response = requests.post(url, data=data)
            if response.ok:
                print(f"[{instance_id}] Message sent successfully")
                return  # Success, exit
            else:
                print(
                    f"[{instance_id}] Failed with {attempt_parse_mode or 'plain text'}: {response.text}"
                )
        except Exception as e:
            print(f"[{instance_id}] Error with {attempt_parse_mode or 'plain text'}: {e}")

    print(f"[{instance_id}] All formatting attempts failed")


def run_claude_code(instance_id, message):
    """Send the message to Claude Code"""
    bot_config = bot_instances[instance_id]
    bot_state = bot_states[instance_id]

    try:
        # Change to markdown folder
        os.chdir(bot_config["markdown_folder"])

        # Add today's date to the message
        today = datetime.now().strftime("%Y-%m-%d")
        message_with_date = f"{message}\n(Today's date is {today})"

        # Start a new session if it's a new day
        if bot_state["last_session_date"] != today:
            bot_state["use_continue_flag"] = False
            bot_state["last_session_date"] = today
            print(f"[{instance_id}] 🔄 New day detected ({today}), starting fresh session")

        print(f"[{instance_id}] Running Claude Code with message:\n{message_with_date}\n")

        # Build command with optional --continue flag
        cmd = ["cmd", "/c", "claude", "--dangerously-skip-permissions"]
        if bot_state["use_continue_flag"]:
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
            bot_state["use_continue_flag"] = True

        if result.returncode != 0:
            print(
                f"[{instance_id}] ❌ Claude Code failed with exit code {result.returncode}\n\nError:\n{result.stderr}\n\nOutput:\n{result.stdout}"
            )
            return None
        print(
            f"[{instance_id}] ✅ Claude Code completed successfully.\n\nOutput:\n{result.stdout}"
        )
        return result.stdout

    except FileNotFoundError:
        print(
            f"[{instance_id}] ❌ Claude CLI not found. Please check if Claude is installed and accessible from PATH."
        )
        return None
    except subprocess.TimeoutExpired:
        print(f"[{instance_id}] ⏱️ Claude Code timed out (took longer than 5 minutes)")
        return None
    except Exception as e:
        print(f"[{instance_id}] Error running Claude Code: {e}")
        return None


def set_webhook(instance_id, ngrok_url, max_retries=3):
    """Set the Telegram webhook for a bot instance with retry logic"""
    import time

    bot_config = bot_instances[instance_id]
    webhook_api_url = f"{bot_config['base_url']}/setWebhook"
    webhook_url = f"{ngrok_url}/webhook/{instance_id}"
    data = {"url": webhook_url, "allowed_updates": ["message"]}

    print(f"[{instance_id}] Setting webhook to: {webhook_url}")

    for attempt in range(max_retries):
        try:
            response = requests.post(
                webhook_api_url,
                json=data,
                timeout=10,
                headers={'Connection': 'close'}
            )
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                print(f"[{instance_id}] ✅ Webhook set successfully")
                return True
            else:
                error_msg = result.get("description", str(result))
                print(f"[{instance_id}] ❌ Failed to set webhook: {error_msg}")
                return False
        except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"[{instance_id}] ⚠️  Connection error (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"[{instance_id}] Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print(f"[{instance_id}] ❌ Failed after {max_retries} attempts")
                print(f"[{instance_id}] ⚠️  Check that:")
                print(f"    1. Your BOT_TOKEN is correct")
                print(f"    2. Your NGROK_URL is accessible: {ngrok_url}")
                print(f"    3. ngrok tunnel is running")
                return False
        except requests.exceptions.RequestException as e:
            print(f"[{instance_id}] ❌ Network error setting webhook: {e}")
            return False
        except Exception as e:
            print(f"[{instance_id}] ❌ Unexpected error setting webhook: {e}")
            import traceback
            traceback.print_exc()
            return False

    return False


def delete_webhook(instance_id):
    """Remove the Telegram webhook for a bot instance"""
    bot_config = bot_instances[instance_id]
    webhook_url = f"{bot_config['base_url']}/deleteWebhook"
    try:
        response = requests.post(webhook_url)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            print(f"[{instance_id}] ✅ Webhook deleted successfully")
            return True
        else:
            print(f"[{instance_id}] ❌ Failed to delete webhook: {result}")
            return False
    except Exception as e:
        print(f"[{instance_id}] ❌ Error deleting webhook: {e}")
        return False


def get_webhook_info(instance_id):
    """Get current webhook info for debugging"""
    bot_config = bot_instances[instance_id]
    webhook_url = f"{bot_config['base_url']}/getWebhookInfo"
    try:
        response = requests.get(webhook_url, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            info = result.get("result", {})
            print(f"[{instance_id}] Webhook Info:")
            print(f"    URL: {info.get('url', 'Not set')}")
            print(f"    Pending updates: {info.get('pending_update_count', 0)}")
            if info.get('last_error_message'):
                print(f"    Last error: {info.get('last_error_message')}")
                print(f"    Last error date: {info.get('last_error_date')}")
            return info
        else:
            print(f"[{instance_id}] Failed to get webhook info: {result}")
            return None
    except Exception as e:
        print(f"[{instance_id}] Error getting webhook info: {e}")
        return None


def process_message(instance_id, msg):
    """Process incoming Telegram message for a specific bot instance"""
    bot_config = bot_instances[instance_id]
    bot_state = bot_states[instance_id]

    # Extract message details
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    # Only process messages from the configured chat
    if str(chat_id) != bot_config["chat_id"]:
        return

    # Handle commands
    if text.startswith("/"):
        if text == "/start":
            send_telegram_message(
                instance_id,
                "🤖 Bot is running! Send me a message to update your markdown files via Claude Code.",
            )
        elif text == "/newsession":
            bot_state["use_continue_flag"] = False
            send_telegram_message(
                instance_id,
                "🔄 Starting a new Claude Code session. Next message will begin a fresh conversation.",
            )
        return

    # Run Claude Code
    result = run_claude_code(instance_id, text)
    if result:
        send_telegram_message(instance_id, result)


@app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "ok": True,
        "message": "Telegram Claude Listener is running",
        "instances": list(bot_instances.keys())
    }), 200


@app.before_request
def log_request():
    """Log all incoming requests"""
    print(f"[REQUEST] {request.method} {request.path} from {request.remote_addr}")


@app.route("/webhook/<instance_id>", methods=["POST", "GET", "HEAD"])
def webhook(instance_id):
    """Handle incoming webhook from Telegram"""
    try:
        # Log all incoming requests with available instances for debugging
        print(f"[{instance_id}] Received {request.method} request to /webhook/{instance_id}")
        print(f"[DEBUG] Available instances: {list(bot_instances.keys())}")
        print(f"[DEBUG] Instance '{instance_id}' exists: {instance_id in bot_instances}")

        # Handle GET/HEAD requests (for testing)
        if request.method in ["GET", "HEAD"]:
            if instance_id in bot_instances:
                print(f"[{instance_id}] {request.method} request received - webhook endpoint is reachable")
                return jsonify({"ok": True, "message": "Webhook endpoint is active"}), 200
            else:
                print(f"[{instance_id}] {request.method} request for unknown instance")
                return jsonify({"ok": False, "error": "Invalid instance ID"}), 404

        # Verify this is a valid instance
        if instance_id not in bot_instances:
            print(f"[{instance_id}] Invalid instance ID - not in configured instances")
            available = ", ".join(bot_instances.keys())
            print(f"[{instance_id}] Available instances: {available}")
            return jsonify({"ok": False, "error": "Invalid instance ID"}), 404

        update = request.get_json()
        print(f"[{instance_id}] Received update: {update}")

        if update and "message" in update:
            process_message(instance_id, update["message"])
        else:
            print(f"[{instance_id}] No message in update")

        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"[{instance_id}] Error in webhook handler: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


def cleanup():
    """Cleanup function to remove all webhooks"""
    print("\n🧹 Cleaning up...")
    for instance_id in bot_instances.keys():
        delete_webhook(instance_id)


def main():
    """Main bot entry point with webhook"""
    global bot_instances

    # Load bot instances from .env
    bot_instances = load_bot_instances()

    if not bot_instances:
        print("❌ No bot instances found in .env file!")
        print("Please create a .env file based on .env.example")
        sys.exit(1)

    # Get ngrok URL from environment
    ngrok_url = os.getenv("NGROK_URL")
    if not ngrok_url:
        print("❌ NGROK_URL not found in .env file!")
        sys.exit(1)

    ngrok_url = ngrok_url.rstrip("/")

    # Register cleanup handler
    atexit.register(cleanup)

    print(f"🤖 Telegram bot listener started!")
    print(f"🌐 Ngrok URL: {ngrok_url}")
    print(f"📊 Loaded {len(bot_instances)} bot instance(s):\n")

    for instance_id, config in bot_instances.items():
        print(f"  [{instance_id}]")
        print(f"    📂 Folder: {config['markdown_folder']}")
        print(f"    💬 Chat ID: {config['chat_id']}")
        print(f"    🔗 Webhook: {ngrok_url}/webhook/{instance_id}\n")

    print("Press Ctrl+C to stop\n")

    try:
        # Set webhooks for all instances
        print("Setting up webhooks...\n")
        for instance_id in bot_instances.keys():
            if not set_webhook(instance_id, ngrok_url):
                print(f"❌ Failed to set webhook for {instance_id}. Continuing anyway...")

        # Verify webhooks were set correctly
        print("\nVerifying webhook configuration...\n")
        for instance_id in bot_instances.keys():
            get_webhook_info(instance_id)
            print()

        # Run Flask app on port 5000
        print("🚀 Starting Flask webhook server on port 5000...")
        print("Press Ctrl+C to stop\n")
        app.run(port=5000, debug=False, use_reloader=False, host='0.0.0.0')

    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except Exception as e:
        print(f"❌ Error in main: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
