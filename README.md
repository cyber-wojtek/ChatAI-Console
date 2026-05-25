# ✦ ChatAI Console

A self-hosted web chat interface for [Claude](https://claude.ai),
[ChatWithAI.app](https://chatwithai.app), [1min.AI](https://1min.ai),
and [Flowith.io](https://flowith.io), powered by the reverse-engineered
`claude_webapi`, `1minai_webapi`, and `flowith_webapi` libraries.

Multi-account management, real-time streaming, file uploads, conversation
branching, usage tracking, and a Galaxy-themed UI — all in a single Quart app.

## Features

- **Multi-Account** — Add, switch, and manage Claude, ChatWithAI, 1min.AI,
  and Flowith accounts. Persisted in Redis (auto-started).
- **Real-Time Streaming** — SSE delivers tokens as generated, with inline
  thinking-block rendering.
- **File Uploads** — Attach files. Upload metadata tracked locally.
- **Conversation Management** — Create, rename, pin, search, branch, and delete.
- **Artifacts & Canvas** — Split-pane preview for code, HTML, SVG, and Mermaid.
- **In-Chat Search** — Search messages with match navigation.
- **Usage & Quota** — Per-account usage snapshots and visual quota bars.
- **Image & Video Generation** — Flowith and 1min.AI generation in-chat.
- **HTTP/2** — Self-signed TLS cert eliminates browser connection-limit stalls.
- **Galaxy UI** — Dark-mode SPA with Space Grotesk and Tokyo Night highlighting.

---

## Quick Start

**Requirements:** Python 3.10+, `redis-server` on PATH

```sh
git clone https://github.com/cyber-wojtek/ChatAI-Console.git
cd ChatAI-Console

# Full setup: installs deps, generates TLS cert, updates .gitignore
python setup.py

# Start the server
python app.py

# Open in browser (accept the self-signed cert warning once)
# Chrome/Edge: Advanced → Proceed to localhost
# Firefox:     Advanced → Accept the Risk
```

Open **https://localhost:5000**, add an account, and start chatting.

> **TLS / HTTP/2** — the self-signed cert is generated locally and never
> leaves your machine. It is valid for 825 days. Run `python setup.py --cert`
> to regenerate it.

---

## Setup Options

```sh
python setup.py           # full setup (recommended)
python setup.py --deps    # only install Python dependencies
python setup.py --cert    # only regenerate TLS cert
python setup.py --check   # only check system requirements
```

---

## Authentication

Accounts are added via the sidebar → account switcher → **Manage Accounts**.

### Claude

**Option A — Session key (manual)**
1. Log in to [claude.ai](https://claude.ai)
2. DevTools (`F12`) → **Application** → **Cookies** → copy `sessionKey`
3. Paste into the session key field (Organization ID is optional)

**Option B — Google sign-in (via extension)**
1. Install the
   [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension)
2. Click **Sign in with Google for Claude** — auth code is filled automatically

### 1min.AI

**Option A — Extract JWT (manual)**
1. Sign in at [app.1min.ai](https://app.1min.ai)
2. DevTools → **Network** → any request to `api.1min.ai`
3. **Request Headers** → `X-Auth-Token: Bearer eyJ…` — copy after `Bearer `

> Token expires after ~7 days.

**Option B — Google sign-in (via extension)**
1. Install the OAuth Bridge extension
2. Click **Sign in with Google for 1min.AI** — JWT is captured automatically

### Flowith.io

**Option A — JWT token (manual)**
1. Sign in at [flowith.io](https://flowith.io) with Google
2. After redirect, copy `access_token` from the URL hash:
   `https://flowith.io/#access_token=eyJ…`

**Option B — Google sign-in (via extension)**
1. Install the OAuth Bridge extension
2. Click **Sign in with Google for Flowith** — token is captured automatically

### Auto-Seeding Accounts

Create `keys.py` in the project root to pre-load accounts on startup:

```python
# keys.py  — never commit this file
ACCOUNTS = [
    ("claude",   "Personal",  "sk-ant-..."),
    ("claude",   "Work",      "org-uuid", "sk-ant-..."),
    ("1minai", "1min",      "eyJ..."),
    ("flowith",  "Flowith",   "eyJ..."),
]
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | New line |
| `Ctrl+Shift+N` | New conversation |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+Shift+K` | Focus search |
| `Escape` | Close modals / canvas |

---

## API Reference

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/ping` | Ping |
| `GET` | `/api/init` | Bootstrap data (accounts + pinned convs in one request) |

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/accounts` | List all accounts |
| `POST` | `/api/accounts` | Add or update account |
| `DELETE` | `/api/accounts/<name>` | Delete account |
| `POST` | `/api/accounts/<name>/activate` | Set active account |

```sh
# Claude — session key
curl -X POST https://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Claude","provider":"claude","session_key":"sk-ant-..."}'

# Claude — Google auth code
curl -X POST https://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Claude","provider":"claude","claude_code":"4/0A..."}'

# 1min.AI
curl -X POST https://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{"name":"My 1min","provider":"oneminai","api_key":"eyJ..."}'

# Flowith
curl -X POST https://localhost:5000/api/accounts \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Flowith","provider":"flowith","api_key":"eyJ..."}'
```

### Conversations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/<id>` | Get conversation with messages |
| `PUT` | `/api/conversations/<id>` | Update conversation |
| `DELETE` | `/api/conversations/<id>` | Delete conversation |
| `PATCH` | `/api/conversations/<id>/rename` | Rename conversation |
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
| `GET` | `/api/local/uploads/<id>` | Upload metadata |
| `POST` | `/api/oneminai/upload` | Upload via 1min.AI Asset API |

### Models

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/models` | Models for active account |
| `GET` | `/api/oneminai/models` | 1min.AI model catalog |
| `GET` | `/api/flowith/models` | Flowith model catalog |

### Usage

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/usage` | Current usage snapshot |
| `GET` | `/api/usage/all` | Usage for all accounts |
| `GET` | `/api/usage/history` | Quota snapshot history |
| `GET` | `/api/usage/messages` | Message log |

### Settings & Preferences

| Method | Endpoint | Description |
|---|---|---|
| `PATCH` | `/api/settings` | Update Claude account settings |
| `GET` | `/api/settings/polling` | Get polling config |
| `PATCH` | `/api/settings/polling` | Update polling config |
| `GET` | `/api/preferences` | Get preferences |
| `PATCH` | `/api/preferences` | Update preferences |

### 1min.AI Generation

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/oneminai/image` | Generate image(s) |
| `POST` | `/api/oneminai/music` | Generate music |
| `POST` | `/api/oneminai/tts` | Text-to-speech |
| `POST` | `/api/oneminai/content-tool` | Grammar / summarize / translate |

### Flowith Generation

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/flowith/image` | Generate image |
| `POST` | `/api/flowith/video` | Generate video |
| `GET` | `/api/flowith/credits` | Credit balance |
| `POST` | `/api/flowith/session-cycle` | Refresh credits |
| `POST` | `/api/flowith/refresh` | Refresh Flowith JWT |

### OAuth (browser extension)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/oauth/claude/begin` | Start Claude OAuth |
| `GET` | `/api/oauth/claude/ext-pending` | Extension polling |
| `POST` | `/api/oauth/claude/ext-callback` | Receive auth code |
| `GET` | `/api/oauth/claude/status` | Poll completion |
| `GET` | `/api/oauth/oneminai/begin` | Start 1min.AI OAuth |
| `GET` | `/api/oauth/oneminai/ext-pending` | Extension polling |
| `POST` | `/api/oauth/oneminai/ext-callback` | Receive Google token |
| `GET` | `/api/oauth/oneminai/status` | Poll completion |
| `GET` | `/api/oauth/flowith/begin` | Start Flowith OAuth |
| `GET` | `/api/oauth/flowith/url` | Supabase OAuth URL |
| `GET` | `/api/oauth/flowith/ext-pending` | Extension polling |
| `POST` | `/api/oauth/flowith/ext-callback` | Receive tokens |
| `GET` | `/api/oauth/flowith/status` | Poll completion |

### Cloudflare Challenge (1min.AI)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/oneminai/cf-pending` | Extension polling |
| `POST` | `/api/oneminai/cf-callback` | Receive cf_clearance |
| `GET` | `/api/oneminai/cf-status` | Poll resolution |

---

## Architecture

```
ChatAI-Console/
├── app.py          # Quart backend — routes, streaming, account management
├── setup.py        # Install helper — deps, cert, .gitignore
├── gen_cert.py     # Standalone cert generator
├── keys.py         # (Optional) auto-seed credentials — never commit
├── cert.pem        # (Generated) TLS cert — never commit
├── key.pem         # (Generated) TLS private key — never commit
└── templates/
    └── index.html  # Single-page Galaxy UI
```

The backend bridges the reverse-engineered APIs and the frontend via REST + SSE.
All four providers share the same conversation/message API surface — the
frontend is provider-agnostic.

---

## Dependencies

| Package | Purpose |
|---|---|
| [Quart](https://quart.palletsprojects.com/) | Async web framework |
| [Hypercorn](https://hypercorn.readthedocs.io/) | HTTP/2 ASGI server |
| [Claude-API](https://github.com/cyber-wojtek/Claude-API/) | Claude.ai client |
| [1MinAI-API](https://github.com/cyber-wojtek/1MinAI-API/) | 1min.AI client |
| [Flowith-API](https://github.com/cyber-wojtek/Flowith-API/) | Flowith.io client |
| [httpx](https://www.python-httpx.org/) | Outbound HTTP |
| [marked.js](https://marked.js.org/) | Markdown rendering |
| [highlight.js](https://highlightjs.org/) | Syntax highlighting |

---

## Related

- [ChatAI Console OAuth Bridge](https://github.com/cyber-wojtek/ChatAI-Console-Extension)
  — Browser extension for Google sign-in
- [1MinAI-API](https://github.com/cyber-wojtek/1MinAI-API/)
- [Flowith-API](https://github.com/cyber-wojtek/Flowith-API/)

---

## License

MIT