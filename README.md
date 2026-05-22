# ✦ ChatAI Console

A self-hosted, free web chat interface for [Claude](https://claude.ai), [ChatWithAI.app](https://chatwithai.app), [1min.AI](https://1min.ai), and [Flowith.io](https://flowith.io), powered by the reverse-engineered `claude_webapi`, `oneminai_webapi` and `flowith_webapi` libraries. Multi-account management, real-time streaming, file uploads, conversation branching, usage tracking, and a Galaxy-themed UI — all in a single Flask app.

## Features

- **Multi-Account** — Add, switch, and manage Claude or MiniApps accounts. Accounts are persisted in a local JSON store.
- **Real-Time Streaming** — Server-Sent Events deliver tokens as they're generated, with inline thinking block rendering.
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
pip install flask claude_webapi 1minai_webapi flowith_webapi hypercorn quart requests
python -m hypercorn app:app --reload --bind localhost:5000 --workers 4
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

### 1min.AI

Two options:

**Option A — Extract JWT from browser (manual)**
1. Sign in at [app.1min.ai](https://app.1min.ai)
2. Open DevTools (`F12`) → **Network**
3. Click any request to `api.1min.ai` (e.g. `/users`)
4. Under **Request Headers**, find `X-Auth-Token: Bearer eyJ…`
5. Copy everything after `Bearer ` — that is your token
6. Paste it into the **API Key** field when adding the account

> The token expires after ~7 days.

**Option B — Google sign-in (via browser extension)**
1. Install the [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension.git) extension
2. Enable the bridge from the extension popup
3. Click **Sign in with Google for 1min.AI** in the account form
4. Complete Google sign-in in the popup — the JWT is captured and filled in automatically

### Flowith.io

Two options:

**Option A — JWT token (manual)**
1. Sign in at [flowith.io](https://flowith.io) with Google
2. After the OAuth redirect, the `access_token` appears in the URL hash:
   `https://flowith.io/#access_token=eyJ…`
3. Copy the token and paste it into the **API Key / Token** field when adding the account

> The token is a Supabase JWT. It remains valid for the duration of your session.

**Option B — Google sign-in (via browser extension)**
1. Install the [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension.git) extension
2. Enable the bridge from the extension popup
3. Click **Sign in with Google for Flowith** in the account form
4. The extension intercepts the Supabase redirect on `flowith.io` and fills in the token automatically

### Auto-Seeding Accounts

Create a `keys.py` in the project root to auto-load accounts on startup:

```python
ACCOUNTS = [
    ("claude", "Account Name", "sk-ant-..."),
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

```sh
# Add Flowith account with JWT token
curl -X POST http://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Flowith",
    "provider": "flowith",
    "api_key": "eyJ..."
  }'```
  Conversations

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
| `POST` | `/api/oneminai/upload` | Upload file via 1min.AI Asset API |

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
| `GET` | `/api/oauth/oneminai/begin` | Start 1min.AI Google OAuth session |
| `GET` | `/api/oauth/oneminai/owns-state` | Check if state belongs to Console |
| `GET` | `/api/oauth/oneminai/ext-pending` | Polled by extension for waiting sessions |
| `POST` | `/api/oauth/oneminai/ext-callback` | Receive Google access token from extension |
| `GET` | `/api/oauth/oneminai/status?state=` | Poll for completed 1min.AI OAuth |

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

The backend bridges the reverse-engineered APIs and the frontend, exposing REST endpoints for account management, conversation handling, file uploads, and OAuth flows. The frontend is a dynamic SPA that consumes these endpoints to provide a seamless chat experience.

## Dependencies

| Package | Purpose |
|---|---|
| [Flask](https://flask.palletsprojects.com/) | Web framework |
| [Claude-API](https://github.com/cyber-wojtek/Claude-API/) | Reverse-engineered async Claude.ai client |
| [1MinAI-API](https://github.com/cyber-wojtek/1MinAI-API/) | Reverse-engineered async 1min.AI client |
| [marked.js](https://marked.js.org/) | Markdown rendering (frontend) |
| [highlight.js](https://highlightjs.org/) | Syntax highlighting (frontend) |

## Related

- [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension.git) — Browser extension for Google sign-in
- [1MinAI-API](https://github.com/cyber-wojtek/1MinAI-API/) — Underlying async Python client for 1min.AI

## License

MIT
