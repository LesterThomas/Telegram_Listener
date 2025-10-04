# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Python-based Telegram bot that listens for messages and forwards them to Claude Code CLI for processing. The bot supports multiple instances running simultaneously on a single Flask server, each operating on different markdown folders and returning Claude Code's responses back to Telegram.

## Configuration

### Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Configure your bot instances in `.env`:
   ```env
   NGROK_URL=https://abc123.ngrok.io

   BOT1_TOKEN=your_bot_token_1
   BOT1_CHAT_ID=your_chat_id_1
   BOT1_MARKDOWN_FOLDER=C:\path\to\markdown\folder1
   BOT1_INSTANCE_ID=bot1

   BOT2_TOKEN=your_bot_token_2
   BOT2_CHAT_ID=your_chat_id_2
   BOT2_MARKDOWN_FOLDER=C:\path\to\markdown\folder2
   BOT2_INSTANCE_ID=bot2
   ```

3. Add as many bot instances as needed following the `BOTx_` prefix pattern

### Running the Bot

The script uses `uv` for dependency management via PEP 723 inline script metadata.

```bash
python telegram_claude_listener.py
```

No command-line arguments are needed - all configuration is loaded from the `.env` file.

## Architecture

### Core Flow
1. **Webhook Reception**: Single Flask app on port 5000 receives webhooks at `/webhook/<instance_id>`
2. **Instance Routing**: Each bot instance is identified by its `INSTANCE_ID` in the webhook URL
3. **Message Processing** (`process_message()`): Validates chat ID and filters out command messages for the specific instance
4. **Claude Code Execution** (`run_claude_code()`): Changes to the instance's markdown folder and runs Claude Code CLI with `--dangerously-skip-permissions` flag
5. **Response Handling** (`send_telegram_message()`): Converts markdown to HTML and sends back to Telegram with fallback formatting options

### Key Implementation Details

- **Multi-Instance Support**: Single Flask app handles all bot instances via unique webhook paths
- **Instance Configuration** (`load_bot_instances()`): Loads bot configurations from environment variables with `BOTx_` prefix pattern
- **State Management**: Each bot instance has its own conversation state tracked in `bot_states` dictionary
- **Daily Session Reset**: Automatically starts a new Claude Code session each day for each bot instance
- **Date Context**: Today's date is appended to every message sent to Claude Code
- **Claude Code Invocation** (`run_claude_code()`): Uses `cmd /c claude` on Windows, changes working directory to instance's `MARKDOWN_FOLDER` before execution, has 5-minute timeout
- **Markdown Conversion** (`convert_markdown_to_html()`): Converts markdown formatting to Telegram HTML, handles Obsidian-style `[[links]]` by converting to underlined text
- **Format Fallback Strategy**: Tries HTML (with conversion), then Markdown, then MarkdownV2, then plain text if formatting fails
- **Chat ID Validation**: Only processes messages from the instance's configured CHAT_ID

### State Management

Per-instance state tracking:
- `use_continue_flag`: Whether to use `--continue` flag for conversation continuity
- `last_session_date`: Date of last session to detect when to start fresh (daily reset)

## Dependencies

Managed via PEP 723 inline metadata:
- Python >=3.11
- `requests` library
- `flask` web framework
- `python-dotenv` for environment variable management

The script is designed to run with `uv run --quiet --script` shebang.
