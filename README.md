<p align="center">
    <img src="https://img.shields.io/badge/ChatAI_Console-Galaxy_UI-8b5cf6?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNhODU1ZjciIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNMTIgMnYyME0yIDEyaDIwTTQuOTMgNC45M2wxNC4xNCAxNC4xNE0xOS4wNyA0LjkzTDQuOTMgMTkuMDciLz48L3N2Zz4=&logoColor=a855f7" alt="ChatAI Console Banner">
</p>
<p align="center">
    <a href="https://www.python.org/downloads/">
        <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+"></a>
    <a href="https://flask.palletsprojects.com/">
        <img src="https://img.shields.io/badge/flask-3.x-green?logo=flask&logoColor=white" alt="Flask"></a>
    <a href="https://github.com/psf/black">
        <img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style"></a>
    <a href="#">
        <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
</p>
<p align="center">
    <img src="https://img.shields.io/badge/Claude-Sonnet%20|%20Opus%20|%20Haiku-8b5cf6?logo=anthropic&logoColor=white" alt="Claude Models">
    <img src="https://img.shields.io/badge/Gemini-Pro%20|%20Flash-4ade80?logo=google&logoColor=white" alt="Gemini Models">
</p>

# ✦ ChatAI Console

A self-hosted web chat console for **[Claude](https://claude.ai)** and **[Google Gemini](https://gemini.google.com)**, powered by reverse-engineered web APIs. Multi-account, real-time streaming, file uploads, usage tracking, and a Galaxy-themed UI — all in a single Flask application.

## Features

- **Multi-Provider** — Seamlessly switch between Claude (Sonnet, Opus, Haiku) and Gemini (Pro, Flash, Flash Thinking) from one unified interface.
- **Multi-Account** — Add, switch, and manage multiple accounts per provider. Accounts are persisted in a local JSON store.
- **Real-Time Streaming** — Server-Sent Events (SSE) streaming for both Claude and Gemini, delivering tokens as they're generated.
- **File Uploads** — Attach images, PDFs, and documents to Claude conversations. Upload metadata is tracked locally.
- **Thinking Blocks** — Visualize extended thinking / chain-of-thought for supported models (Claude Sonnet with extended thinking, Gemini Flash Thinking).
- **Conversation Management** — Create, rename, pin, search, branch, and delete conversations. Full chat history with message timestamps.
- **Usage & Quota Tracking** — Monitor per-account usage, quota snapshots, and message history with visual quota bars.
- **Artifacts & Canvas** — Inline artifact rendering with a split-pane canvas preview for code, HTML, SVG, and Mermaid diagrams.
- **Galaxy-Themed UI** — A polished, dark-mode single-page app built with Space Grotesk, JetBrains Mono, and Tokyo Night syntax highlighting.
- **Keyboard Shortcuts** — `Ctrl+Enter` to send, `Ctrl+Shift+N` for new chat, `Ctrl+B` to toggle sidebar, and more.
- **Local-First Storage** — All account data, conversation indexes, and preferences stored in `data/accounts.json`. No external database required.

## Table of Contents

- [✦ ChatAI Console](#-chatai-console)
  - [Features](#features)
  - [Table of Contents](#table-of-contents)
  - [Screenshots](#screenshots)
  - [Installation](#installation)
  - [Authentication](#authentication)
    - [Claude](#claude)
    - [Gemini](#gemini)
  - [Usage](#usage)
    - [Running the Server](#running-the-server)
    - [Adding Accounts](#adding-accounts)
    - [Starting a Conversation](#starting-a-conversation)
    - [Switching Models](#switching-models)
    - [File Attachments](#file-attachments)
    - [Extended Thinking](#extended-thinking)
    - [Web Search](#web-search)
    - [Conversation Branching](#conversation-branching)
    - [Keyboard Shortcuts](#keyboard-shortcuts)
  - [Configuration](#configuration)
    - [Environment Variables](#environment-variables)
    - [Preferences](#preferences)
  - [API Reference](#api-reference)
    - [Health](#health)
    - [Accounts](#accounts)
    - [Conversations](#conversations)
    - [Messages](#messages)
    - [File Handling](#file-handling)
    - [Usage \& Quota](#usage--quota)
    - [Settings](#settings)
  - [Architecture](#architecture)
  - [Dependencies](#dependencies)
  - [References](#references)

## Screenshots

> *Galaxy-themed dark UI with real-time streaming, artifact canvas, and multi-account sidebar.*

## Installation

> [!NOTE]
>
> This application requires **Python 3.10** or higher.

1. **Clone the repository**

```sh
git clone https://github.com/your-username/chatai-console.git
cd chatai-console
```

2. **Install dependencies**

```sh
pip install flask claude_webapi gemini_webapi
```

Or install from the included `claude_webapi` package:

```sh
cd claude_webapi
pip install -e .
cd ..
pip install flask gemini_webapi
```

3. **Run the application**

```sh
cd chatai_console
python app.py
```

4. **Open in browser**

```
http://localhost:5000
```

## Authentication

### Claude

To use Claude, you need a valid session key and organization ID from [claude.ai](https://claude.ai):

1. Go to <https://claude.ai> and log in with your account
2. Press **F12** to open Developer Tools → **Application** tab → **Cookies**
3. Copy the value of the `sessionKey` cookie
4. For organization ID, go to **Network** tab, click any API request, and find the `orgId` in the request URL (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

> [!TIP]
>
> You can also seed accounts automatically by creating a `keys.py` file in the `chatai_console` directory. See [Environment Variables](#environment-variables) for details.

### Gemini

To use Gemini, you need cookies from [gemini.google.com](https://gemini.google.com):

1. Go to <https://gemini.google.com> and log in with your Google account
2. Press **F12** → **Application** tab → **Cookies**
3. Copy the values of `__Secure-1PSID` and `__Secure-1PSIDTS`

> [!NOTE]
>
> Gemini cookies may expire periodically. The `gemini_webapi` library supports automatic cookie refreshing in the background for long-running services.

## Usage

### Running the Server

```sh
cd chatai_console
python app.py
```

The server starts on `http://localhost:5000` by default. All data is persisted to `data/accounts.json`.

### Adding Accounts

You can add accounts through the UI:

1. Click the **account switcher** at the bottom of the sidebar
2. Click **＋ Add Account** in the dropdown menu
3. Select provider (`claude` or `gemini`) and enter your credentials

Or via the API:

```sh
# Add a Claude account
curl -X POST http://localhost:5000/api/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Claude",
    "provider": "claude",
    "session_key": "sk-ant-...",
    "organization_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  }'

# Add a Gemini account
curl -X POST http://localhost:5000/api/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Gemini",
    "provider": "gemini",
    "secure_1psid": "...",
    "secure_1psidts": "..."
  }'
```

### Starting a Conversation

- Click the **＋ New Chat** button in the sidebar, or
- Click **Start chatting** on the splash screen, or
- Press **Ctrl+Shift+N**
- Type your message and press **Ctrl+Enter** to send

### Switching Models

Use the **model selector** dropdown in the toolbar to switch between available models:

| Provider | Models |
|----------|--------|
| **Claude** | `claude-sonnet-4-20250514`, `claude-opus-4-20250514`, `claude-haiku-3.5-20241022` |
| **Gemini** | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash-thinking` |

### File Attachments

For Claude conversations, you can attach files to your messages:

1. Click the **📎** button in the message input area
2. Select one or more files (images, PDFs, documents)
3. Files are uploaded to the Claude API and included with your next message

> [!NOTE]
>
> File uploads are currently supported for Claude accounts only. Maximum file size is **100 MB**.

### Extended Thinking

Enable extended thinking (chain-of-thought) for supported models:

1. Click the **💭 Think** toggle in the toolbar
2. Optionally adjust the thinking budget with the extended thinking control
3. Thinking blocks will appear as collapsible sections above the response

> [!TIP]
>
> Extended thinking works with Claude Sonnet (budget configurable) and Gemini Flash Thinking (always enabled for that model).

### Web Search

Toggle web search capability for Claude models:

1. Click the **🔍 Search** toggle in the toolbar
2. Claude will use web search when relevant to your query

### Conversation Branching

Edit a previous message to create a branch in the conversation:

1. Hover over a message and click the **✏️ Edit** button
2. Modify the message and resend
3. Use the branch navigator in the toolbar to switch between branches

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Send message |
| `Ctrl+Shift+N` | New conversation |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+Shift+K` | Focus search |
| `Escape` | Close modals / canvas |

## Configuration

### Environment Variables

Create a `keys.py` file in the `chatai_console` directory to auto-seed accounts on startup:

```python
# filepath: chatai_console/keys.py

# Claude accounts
CLAUDE_SESSION_KEY = "sk-ant-..."
CLAUDE_ORG_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Gemini accounts
GEMINI_1PSID = "..."
GEMINI_1PSIDTS = "..."
```

### Preferences

User preferences are stored per-account and can be configured via the API:

```sh
curl -X PATCH http://localhost:5000/api/preferences \
  -H "Content-Type: application/json" \
  -d '{"default_model": "claude-sonnet-4-20250514", "theme": "galaxy"}'
```

## API Reference

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |

### Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/accounts` | List all accounts |
| `POST` | `/api/accounts` | Add a new account |
| `DELETE` | `/api/accounts/<name>` | Delete an account |
| `POST` | `/api/accounts/<name>/activate` | Set account as active |

### Conversations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/conversations` | List conversations for active account |
| `POST` | `/api/conversations` | Create a new conversation |
| `GET` | `/api/conversations/<id>` | Get conversation details |
| `PUT` | `/api/conversations/<id>` | Update conversation (rename, etc.) |
| `POST` | `/api/conversations/<id>/stop` | Stop active generation |

### Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/conversations/<id>/messages` | Send a message (SSE streaming response) |

**Request body:**

```json
{
  "prompt": "Hello, how are you?",
  "model": "claude-sonnet-4-20250514",
  "thinking": false,
  "search": false,
  "files": []
}
```

### File Handling

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/conversations/<id>/upload` | Upload a file (Claude only) |
| `GET` | `/api/conversations/<id>/download` | Download a sandbox file |
| `GET` | `/api/local/uploads/<id>` | Get upload metadata |

### Usage & Quota

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/usage` | Get current usage / quota snapshot |
| `GET` | `/api/usage/history` | Get quota history over time |
| `GET` | `/api/usage/messages` | Get per-message usage log |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PATCH` | `/api/settings` | Update Claude account settings |
| `GET` | `/api/preferences` | Get user preferences |
| `PATCH` | `/api/preferences` | Update user preferences |

## Architecture

```
chatai_console/
├── app.py                  # Flask backend — routes, streaming, account management
├── data/
│   └── accounts.json       # Persistent JSON store (auto-created)
├── templates/
│   └── index.html          # Single-page Galaxy-themed UI
├── keys.py                 # (Optional) Auto-seed credentials

claude_webapi/              # Async Python wrapper for Claude.ai web API
├── claude_webapi/
│   ├── __init__.py
│   ├── client.py           # ClaudeClient — main entry point
│   ├── session.py          # ChatSession — multi-turn conversations
│   ├── constants.py        # Model enum, base URLs
│   └── exceptions.py       # APIError, AuthenticationError, QuotaExceededError
├── setup.py
└── examples.py
```

**Key design decisions:**

- **Thread-safe JSON store** — `JSONStore` class with locking for concurrent Flask requests
- **Async bridge** — Dedicated `asyncio` event loop on a background thread (`_run()` helper) to bridge sync Flask handlers with async `claude_webapi` / `gemini_webapi` clients
- **SSE streaming** — Both providers emit `data: {...}\n\n` server-sent events with a unified format, consumed by the frontend's `EventSource`
- **Local conversation index** — Gemini conversations are tracked locally (the Gemini web API doesn't provide full conversation management), while Claude conversations are fetched from the API

## Dependencies

| Package | Purpose |
|---------|---------|
| [Flask](https://flask.palletsprojects.com/) | Web framework and HTTP server |
| [claude_webapi](claude_webapi/) | Reverse-engineered async Claude.ai client |
| [gemini_webapi](https://github.com/HanaokaYuzu/Gemini-API) | Reverse-engineered async Gemini client |
| [marked.js](https://marked.js.org/) | Markdown rendering in the frontend |
| [highlight.js](https://highlightjs.org/) | Syntax highlighting (Tokyo Night Dark theme) |
| [Inter / JetBrains Mono / Space Grotesk](https://fonts.google.com/) | UI typography |

## References

- [Claude.ai](https://claude.ai) — Anthropic's AI assistant
- [Google Gemini](https://gemini.google.com) — Google's AI assistant
- [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) — Gemini web API wrapper
- [Flask Documentation](https://flask.palletsprojects.com/)