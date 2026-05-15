# ✦ ChatAI Console

A self-hosted web chat interface for [Claude](https://claude.ai) and [MiniApps.ai](https://miniapps.ai), powered by the reverse-engineered `claude_webapi` and `miniapps_api` libraries. Multi-account management, real-time streaming, file uploads, conversation branching, usage tracking, and a Galaxy-themed UI — all in a single Flask app.

## Features

- **Multi-Account** — Add, switch, and manage Claude or MiniApps accounts. Accounts are persisted in a local JSON store.
- **Real-Time Streaming** — Server-Sent Events deliver tokens as they're generated, with inline thinking block rendering.
- **All Claude Models** — Sonnet 4-6, Opus 4-6, Haiku 4-5, Sonnet 3-7, Opus 4-5, and Sonnet 3-5.
- **Extended Thinking** — Toggle chain-of-thought. Thinking blocks render as collapsible sections.
- **File Uploads** — Attach  files up to 100 MB. Upload metadata tracked locally.
- **Conversation Management** — Create, rename, pin, search, branch, and delete conversations.
- **Artifacts & Canvas** — Split-pane canvas preview for code, HTML, SVG, and Mermaid diagram artifacts.
- **In-Chat Search** — Search within the current conversation with match navigation.
- **Usage & Quota Tracking** — Per-account usage snapshots, message history, and visual quota bars in the sidebar.
- **Galaxy UI** — Dark-mode SPA built with Space Grotesk, JetBrains Mono, and Tokyo Night syntax highlighting.
- **Local-First** — All data lives in `data/accounts.json`. No external database.

## Quick Start

**Requirements:** Python 3.10+

```sh
git clone https://github.com/cyber-wojtek/ChatAI-Console.git
cd ChatAI-Console
pip install flask claude_webapi
python app.py
```

Open **http://localhost:5000**, add an account, and start chatting.

## Authentication

Accounts are added via the sidebar → account switcher → **＋ Add Account**.

### Claude

Two options:

**Option A — Session key (manual)**
1. Log in to claude.ai
2. Open DevTools (`F12`) → **Application** → **Cookies**
3. Copy the `sessionKey` value and paste it into the session key field
4. Organization ID is optional — discovered automatically if omitted

**Option B — Google sign-in (via browser extension)**
1. Install the [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension.git) extension
2. Enable the bridge from the extension popup
3. Click **Sign in with Google for Claude** in the account form
4. Complete Google sign-in in the popup — the auth code is filled in automatically

### Auto-Seeding Accounts

Create a `keys.py` in the project root to auto-load accounts on startup:

```python
CLAUDE_ACCOUNTS = [
    ("Account Name", "sk-ant-..."),
    ("Account Name With Org", "org-uuid", "sk-ant-..."),
]
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | New line |
| `Ctrl+Shift+N` | New conversation |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+Shift+K` | Focus search |
| `Escape` | Close modals / canvas |

## API Reference

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/accounts` | List all accounts |
| `POST` | `/api/accounts` | Add account |
| `DELETE` | `/api/accounts/<name>` | Delete account |
| `POST` | `/api/accounts/<name>/activate` | Set active account |

```sh
# Add Claude account with session key
curl -X POST http://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Claude",
    "provider": "claude",
    "session_key": "sk-ant-...",
    "organization_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  }'

# Add Claude account via Google auth code (from OAuth flow)
curl -X POST http://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Claude",
    "provider": "claude",
    "claude_code": "4/0A..."
  }'

# Add MiniApps account
curl -X POST http://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "MiniApps",
    "provider": "miniapps",
    "miniapps_id_token": "eyJ...",
    "tool_slug": "claude-37"
  }'
```

### Conversations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/<id>` | Get conversation |
| `PUT` | `/api/conversations/<id>` | Update conversation |
| `POST` | `/api/conversations/<id>/stop` | Stop generation |

### Messages

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/conversations/<id>/messages` | Send message (SSE stream) |

### Files

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/conversations/<id>/upload` | Upload file |
| `GET` | `/api/conversations/<id>/download` | Download sandbox file |
| `GET` | `/api/local/uploads/<id>` | Get upload metadata |

### Usage

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/usage` | Current usage snapshot |
| `GET` | `/api/usage/history` | Quota history |
| `GET` | `/api/usage/messages` | Message log |

### Settings & Preferences

| Method | Endpoint | Description |
|---|---|---|
| `PATCH` | `/api/settings` | Update Claude account settings |
| `GET` | `/api/preferences` | Get preferences |
| `PATCH` | `/api/preferences` | Update preferences |

### OAuth (used by the browser extension)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/oauth/claude/begin` | Start Claude Google OAuth session |
| `GET` | `/api/oauth/claude/ext-pending` | Polled by extension to find waiting Claude sessions |
| `POST` | `/api/oauth/claude/ext-callback` | Receive auth code from extension |
| `GET` | `/api/oauth/claude/status?state=` | Poll for completed Claude OAuth |
| `GET` | `/api/oauth/miniapps/begin` | Start MiniApps Google OAuth session |
| `GET` | `/api/oauth/miniapps/ext-pending` | Polled by extension to find waiting sessions |
| `POST` | `/api/oauth/miniapps/ext-callback` | Receive ID token from extension |
| `GET` | `/api/oauth/miniapps/status?state=` | Poll for completed MiniApps OAuth |

## Architecture

```
ChatAI-Console/
├── app.py                  # Flask backend — routes, streaming, account management
├── keys.py                 # (Optional) auto-seed account credentials
├── data/
│   └── accounts.json       # Persistent JSON store (auto-created)
└── templates/
    └── index.html          # Single-page Galaxy-themed frontend
```

The backend bridges sync Flask handlers to the async `claude_webapi` client via a dedicated `asyncio` event loop on a background thread. Streaming uses SSE with a unified `data: {...}\n\n` format consumed by the frontend's `EventSource`.

## Dependencies

| Package | Purpose |
|---|---|
| [Flask](https://flask.palletsprojects.com/) | Web framework |
| [Claude-API](https://github.com/cyber-wojtek/Claude-API/) | Reverse-engineered async Claude.ai client |
| [MiniappsAI-API](https://github.com/cyber-wojtek/MiniappsAI-API/) | Reverse-engineered MiniApps.ai client |
| [marked.js](https://marked.js.org/) | Markdown rendering (frontend) |
| [highlight.js](https://highlightjs.org/) | Syntax highlighting (frontend) |

## Related

- [ChatAI Console OAuth Bridge](../ChatAI-Console-Extension/) — Browser extension for Google sign-in

## License

MIT
