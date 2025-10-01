# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Python-based Telegram bot that listens for messages and forwards them to Claude Code CLI for processing. The bot operates on a markdown folder and returns Claude Code's responses back to Telegram.

## Running the Bot

The script uses `uv` for dependency management via PEP 723 inline script metadata.

```bash
python telegram_claude_listener.py <BOT_TOKEN> <CHAT_ID> <MARKDOWN_FOLDER>
```

Example:
```bash
python telegram_claude_listener.py 'your_bot_token' 'your_chat_id' 'C:\path\to\markdown\folder'
```

Required arguments:
- `BOT_TOKEN`: Telegram bot API token
- `CHAT_ID`: Telegram chat ID to monitor
- `MARKDOWN_FOLDER`: Directory where Claude Code will operate

## Architecture

### Core Flow
1. **Telegram Polling** (`get_updates()`): Long-polls Telegram API every 10 seconds for new messages
2. **Message Processing** (`process_message()`): Validates chat ID and filters out command messages
3. **Claude Code Execution** (`run_claude_code()`): Changes to the markdown folder and runs Claude Code CLI with `--dangerously-skip-permissions` flag
4. **Response Handling** (`send_telegram_message()`): Converts markdown to HTML and sends back to Telegram with fallback formatting options

### Key Implementation Details

- **Claude Code Invocation** (line 116): Uses `cmd /c claude` on Windows, changes working directory to `MARKDOWN_FOLDER` before execution, has 5-minute timeout
- **Markdown Conversion** (`convert_markdown_to_html()`): Converts markdown formatting to Telegram HTML, handles Obsidian-style `[[links]]` by converting to underlined text
- **Format Fallback Strategy**: Tries HTML (with conversion), then Markdown, then MarkdownV2, then plain text if formatting fails
- **Chat ID Validation** (line 174): Only processes messages from the specified CHAT_ID

### State Management

- `last_update_id`: Global variable tracking the last processed Telegram update to avoid reprocessing messages

## Dependencies

Managed via PEP 723 inline metadata:
- Python >=3.11
- `requests` library

The script is designed to run with `uv run --quiet --script` shebang.
