# ✦ Claude Console

A self-hosted web chat interface for [Claude](https://claude.ai), powered by the reverse-engineered `claude_webapi` library. Multi-account management, real-time streaming, file uploads, conversation branching, usage tracking, and a Galaxy-themed UI — all in a single Flask app.

## Features

- **Multi-Account** — Add, switch, and manage multiple Claude accounts. Accounts are persisted in a local JSON store.
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
git clone <repo-url>
git clone <Claude-API url>
cd ChatAI-Console
pip install flask
pip install ../Claude-API/
python app.py
```

Open **http://localhost:5000**, add an account, and start chatting.

## Authentication

You need a session key and organization ID from [claude.ai](https://claude.ai):

1. Log in to claude.ai
2. Open DevTools (`F12`) → **Application** → **Cookies**
3. Copy the `sessionKey` value
4. For the org ID, check the **Network** tab — find any API request URL containing `/organizations/<uuid>` or use `lastActiveOrg` cookie value.

Add credentials through the UI (sidebar → account switcher → ＋ Add Account) or via the API:

```sh
curl -X POST http://localhost:5000/api/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Account",
    "provider": "claude",
    "session_key": "sk-ant-...",
    "organization_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  }'
```

### Auto-Seeding Accounts

Create a `keys.py` in the project root to auto-load accounts on startup:

```python
CLAUDE_ACCOUNTS = [
    ("Account Name", "org-uuid", "sk-ant-..."),
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
| [claude_webapi](https://github.com/cyber-wojtek/Claude-API/) | Reverse-engineered async Claude.ai client |
| [marked.js](https://marked.js.org/) | Markdown rendering (frontend) |
| [highlight.js](https://highlightjs.org/) | Syntax highlighting (frontend) |

## License

MIT
