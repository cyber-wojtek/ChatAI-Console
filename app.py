"""
Claude Console — Web UI Backend  v4
Powered by claude_webapi.

Run:  python app.py
Open: http://localhost:5000
Data: ./data/accounts.json
"""

import asyncio
import json
import logging
import os
import threading
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, Response, jsonify, render_template, request,
    stream_with_context,
)
import requests as http_client

from claude_webapi import ClaudeClient
from claude_webapi.constants import CLAUDE_BASE_URL
from claude_webapi.exceptions import (
    APIError, AuthenticationError, QuotaExceededError,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("claude-console")

# ═══════════════════════════════════════════════════════════════════════════════
# JSON Store
# ═══════════════════════════════════════════════════════════════════════════════

STORE_PATH = Path(__file__).parent / "data" / "accounts.json"
STORE_PATH.parent.mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class JSONStore:
    """Thread-safe JSON file store for all application data."""

    def __init__(self, path: Path):
        self.path  = path
        self._lock = threading.Lock()
        self._data = self._load()
        log.info("JSON store ready  %s", self.path)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data.setdefault("accounts", [])
                    return data
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load %s: %s  — starting fresh", self.path, e)
        return {"accounts": []}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def read(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def mutate(self, fn):
        with self._lock:
            fn(self._data)
            self._save()


store = JSONStore(STORE_PATH)


# ═══════════════════════════════════════════════════════════════════════════════
# Async event loop bridge
# ═══════════════════════════════════════════════════════════════════════════════

_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True, name="async-loop")
_loop_thread.start()


def _run(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()


# ═══════════════════════════════════════════════════════════════════════════════
# Claude client + streaming
# ═══════════════════════════════════════════════════════════════════════════════

def _make_claude_client(acct: dict) -> ClaudeClient:
    sk  = acct.get("session_key", "")
    org = acct.get("organization_id", "")
    if not sk or not org:
        raise ValueError(f"Account '{acct.get('name', '?')}' is missing session_key or organization_id")
    client = ClaudeClient(sk, org)
    _run(client.init(timeout=60, auto_close=True, close_delay=120))
    return client


def _sync_stream_claude(acct: dict, conv_id: str, payload: dict):
    import queue as _queue

    client       = _make_claude_client(acct)
    q: "_queue.Queue" = _queue.Queue()
    account_name = acct["name"]

    async def producer():
        try:
            url  = client._org_url(f"chat_conversations/{conv_id}/completion")
            body = json.dumps(payload).encode()
            session = client._ensure_session()
            async with session.post(
                url, data=body,
                headers={"Accept": "text/event-stream",
                         "Content-Length": str(len(body))},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    q.put(APIError(f"Completion HTTP {resp.status}: {text[:300]}",
                                   status_code=resp.status))
                    return
                async for raw_chunk, _ in resp.content.iter_chunks():
                    if not raw_chunk:
                        continue
                    q.put(raw_chunk)
                    try:
                        text = raw_chunk.decode("utf-8", errors="replace")
                        for line in text.splitlines():
                            if not line.startswith("data:"):
                                continue
                            js = line[5:].strip()
                            if not js:
                                continue
                            try:
                                evt = json.loads(js)
                            except json.JSONDecodeError:
                                continue
                            if evt.get("type") == "message_limit":
                                ml = evt.get("message_limit")
                                if ml:
                                    _save_quota_snapshot(account_name, ml)
                    except Exception:
                        pass
        except Exception as exc:
            q.put(exc)
        finally:
            q.put(None)
            await client.close()

    asyncio.run_coroutine_threadsafe(producer(), _loop)

    while True:
        item = q.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


# ═══════════════════════════════════════════════════════════════════════════════
# Claude message payload builder
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_TOOLS = [
    {"name": "web_search",            "type": "web_search_v0"},
    {"name": "artifacts",             "type": "artifacts_v0"},
    {"name": "repl",                  "type": "repl_v0"},
    {"name": "ask_user_input_v0",     "type": "widget"},
    {"name": "weather_fetch",         "type": "widget"},
    {"name": "recipe_display_v0",     "type": "widget"},
    {"name": "places_map_display_v0", "type": "widget"},
    {"name": "message_compose_v1",    "type": "widget"},
    {"name": "places_search",         "type": "widget"},
    {"name": "fetch_sports_data",     "type": "widget"},
]

_DEFAULT_STYLE = {
    "isDefault": True, "key": "default", "name": "Normal",
    "nameKey": "normal_style_name", "prompt": "Normal\n",
    "summary": "Default responses from Claude",
    "summaryKey": "normal_style_summary", "type": "default",
}


def build_claude_payload(data: dict) -> dict:
    raw_files = data.get("files") or []
    files = []
    for f in raw_files:
        if isinstance(f, str):
            files.append(f)
        elif isinstance(f, dict):
            fid = f.get("file_uuid") or f.get("id") or f.get("file_id")
            if fid:
                files.append(fid)
    return {
        "files":               files,
        "locale":              data.get("locale", "en-US"),
        "model":               data.get("model", "claude-sonnet-4-6"),
        "parent_message_uuid": data.get("parent_message_uuid",
                                        "00000000-0000-4000-8000-000000000000"),
        "personalized_styles": [_DEFAULT_STYLE],
        "prompt":              data.get("prompt", ""),
        "rendering_mode":      "messages",
        "sync_sources":        [],
        "timezone":            data.get("timezone", "UTC"),
        "tools":               _DEFAULT_TOOLS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Account helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _new_account(name: str, provider: str, **creds) -> dict:
    base = {
        "name":       name,
        "provider":   provider,
        "is_active":  False,
        "created_at": _now(),
    }
    base.update(creds)
    return base


def _set_active_in_data(data, name):
    for a in data["accounts"]:
        a["is_active"] = (a["name"] == name)


def _get_active_account() -> dict | None:
    data = store.read()
    for a in data["accounts"]:
        if a.get("is_active"):
            return a
    return None


def _ensure_single_active(name: str):
    def fn(data):
        for a in data["accounts"]:
            a["is_active"] = (a["name"] == name)
    store.mutate(fn)


def _get_account_by_name(name: str) -> dict | None:
    data = store.read()
    return next((a for a in data["accounts"] if a["name"] == name), None)


def _account_to_public(a: dict) -> dict:
    pub: dict = {
        "name":            a["name"],
        "provider":        "claude",
        "active":          bool(a.get("is_active")),
        "created_at":      a.get("created_at", ""),
        "session_key":     a.get("session_key", ""),
        "organization_id": a.get("organization_id", ""),
    }
    return pub


def _seed_from_env():
    try:
        from keys import CLAUDE_ACCOUNTS
    except ImportError:
        return
    if not CLAUDE_ACCOUNTS:
        return

    def fn(data):
        for name, org_id, session_key in CLAUDE_ACCOUNTS:
            if not any(a["name"] == name for a in data["accounts"]):
                data["accounts"].append(
                    _new_account(name, "claude",
                                 session_key=session_key,
                                 organization_id=org_id)
                )
                log.info("Seeded Claude account: %s", name)
        if not any(a.get("is_active") for a in data["accounts"]):
            if data["accounts"]:
                data["accounts"][0]["is_active"] = True
    store.mutate(fn)


_seed_from_env()


# ═══════════════════════════════════════════════════════════════════════════════
# Quota / usage helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _save_quota_snapshot(account_name: str, payload: dict):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == account_name:
                snaps = a.setdefault("usage_snapshots", [])
                snaps.append({"snapshot": payload, "captured_at": _now()})
                a["usage_snapshots"] = snaps[-200:]
                break
    store.mutate(fn)


def _get_latest_quota(account_name: str) -> dict | None:
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == account_name:
            snaps = a.get("usage_snapshots", [])
            if snaps:
                last = snaps[-1]
                snap = dict(last["snapshot"])
                snap["_captured_at"] = last["captured_at"]
                return snap
    return None


def _log_message_send(account_name: str, conv_uuid: str, model: str, prompt_len: int):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == account_name:
                entries = a.setdefault("message_log", [])
                entries.append({
                    "conv_uuid":  conv_uuid,
                    "model":      model,
                    "prompt_len": prompt_len,
                    "sent_at":    _now(),
                })
                a["message_log"] = entries[-500:]
                break
    store.mutate(fn)


def _save_upload_meta(acct_name, conv_uuid, file_uuid, filename, size, content_type):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct_name:
                uploads = a.setdefault("file_uploads", [])
                next_id = max((u.get("id", 0) for u in uploads), default=0) + 1
                uploads.append({
                    "id":           next_id,
                    "conv_uuid":    conv_uuid,
                    "file_uuid":    file_uuid,
                    "filename":     filename,
                    "size":         size,
                    "content_type": content_type,
                    "uploaded_at":  _now(),
                })
                break
    store.mutate(fn)


# ═══════════════════════════════════════════════════════════════════════════════
# Flask App
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


def require_account(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        acct = _get_active_account()
        if not acct:
            return jsonify({"error": "No active account configured"}), 401
        if not acct.get("session_key") or not acct.get("organization_id"):
            return jsonify({"error": "Active account is missing Claude credentials (session_key / organization_id). "
                            "Please switch to a valid Claude account or re-add this one."}), 401
        return fn(acct, *args, **kwargs)
    return wrapper


def api_error_handler(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AuthenticationError as exc:
            log.warning("Auth error: %s", exc)
            return jsonify({"error": "Authentication failed — check your credentials"}), 401
        except APIError as exc:
            log.warning("API error HTTP %s: %s", exc.status_code, exc)
            return jsonify({"error": str(exc), "status": exc.status_code}), exc.status_code or 500
        except QuotaExceededError as exc:
            return jsonify({"error": str(exc)}), 429
        except http_client.Timeout:
            return jsonify({"error": "Upstream request timed out"}), 504
        except http_client.ConnectionError:
            return jsonify({"error": "Cannot reach upstream API"}), 502
        except Exception as exc:
            log.exception("Unhandled error in %s", fn.__name__)
            return jsonify({"error": str(exc)}), 500
    return wrapper


# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    acct = _get_active_account()
    return jsonify({
        "status":   "ok",
        "store":    str(STORE_PATH),
        "account":  acct["name"]               if acct else None,
        "provider": acct.get("provider","claude") if acct else None,
    })


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/c/<path:conv_id>")
def index(conv_id=None):
    return render_template("index.html")


# ── Accounts ──────────────────────────────────────────────────────────────────

@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    data    = store.read()
    accounts = data["accounts"]
    active  = next((a["name"] for a in accounts if a.get("is_active")), None)
    return jsonify({
        "accounts": [_account_to_public(a)
                     for a in sorted(accounts, key=lambda x: x.get("created_at",""))],
        "active": active,
    })


@app.route("/api/accounts", methods=["POST"])
def add_account():
    req  = request.json or {}
    name = (req.get("name") or "").strip()
    sk   = (req.get("session_key")     or "").strip()
    org  = (req.get("organization_id") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not sk:
        return jsonify({"error": "session_key is required"}), 400
    if not org:
        return jsonify({"error": "organization_id is required"}), 400

    active_name = None

    def fn(data):
        nonlocal active_name
        existing = next((a for a in data["accounts"] if a["name"] == name), None)
        if existing:
            existing.update({"provider": "claude",
                             "session_key": sk,
                             "organization_id": org})
        else:
            data["accounts"].append(
                _new_account(name, "claude",
                             session_key=sk, organization_id=org))
        if req.get("activate") or len(data["accounts"]) == 1:
            _set_active_in_data(data, name)
        active_name = next(
            (a["name"] for a in data["accounts"] if a.get("is_active")), None)

    store.mutate(fn)
    log.info("Account saved: %s provider=claude active=%s", name, active_name == name)
    return jsonify({"success": True, "name": name,
                    "active": active_name == name}), 201


@app.route("/api/accounts/<n>", methods=["DELETE"])
def delete_account(n):
    if not _get_account_by_name(n):
        return jsonify({"error": "Account not found"}), 404
    active_name = None

    def fn(data):
        nonlocal active_name
        was_active = any(a["name"] == n and a.get("is_active")
                         for a in data["accounts"])
        data["accounts"] = [a for a in data["accounts"] if a["name"] != n]
        if was_active and data["accounts"]:
            data["accounts"].sort(key=lambda a: a.get("created_at", ""))
            data["accounts"][0]["is_active"] = True
        active_name = next(
            (a["name"] for a in data["accounts"] if a.get("is_active")), None)

    store.mutate(fn)
    return jsonify({"success": True, "active": active_name})


@app.route("/api/accounts/<n>/activate", methods=["POST"])
def activate_account(n):
    if not _get_account_by_name(n):
        return jsonify({"error": "Account not found"}), 404
    _ensure_single_active(n)
    log.info("Switched active account → %s", n)
    return jsonify({"success": True, "active": n})


# ── Legacy config ─────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def get_config():
    acct = _get_active_account()
    return jsonify({
        "session_key_set": bool(acct and acct.get("session_key")),
        "organization_id": acct.get("organization_id", "") if acct else "",
        "active_account":  acct["name"] if acct else None,
        "provider":        "claude",
        "configured":      bool(acct),
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}
    acct = _get_active_account()
    name = (data.get("name") or (acct["name"] if acct else "default")).strip()
    sk   = (data.get("session_key") or "").strip()
    org  = (data.get("organization_id") or "").strip()

    def fn(store_data):
        existing = next((a for a in store_data["accounts"] if a["name"] == name), None)
        if existing:
            if sk:  existing["session_key"]     = sk
            if org: existing["organization_id"] = org
            existing.setdefault("provider", "claude")
        else:
            store_data["accounts"].append(
                _new_account(name, "claude",
                             session_key=sk or "", organization_id=org or ""))
        _set_active_in_data(store_data, name)

    store.mutate(fn)
    return jsonify({"success": True, "active": name})


# ── Preferences ───────────────────────────────────────────────────────────────

@app.route("/api/preferences", methods=["GET"])
@require_account
def get_preferences(acct):
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            return jsonify(a.get("preferences", {}))
    return jsonify({})


@app.route("/api/preferences", methods=["PATCH"])
@require_account
def set_preferences(acct):
    prefs = request.json or {}

    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                a.setdefault("preferences", {}).update(prefs)
                break

    store.mutate(fn)
    return jsonify({"success": True})


# ── Conversations ─────────────────────────────────────────────────────────────

@app.route("/api/conversations", methods=["GET"])
@require_account
@api_error_handler
def list_conversations(acct):
    client = _make_claude_client(acct)
    try:
        convs = _run(client.list_conversations())
        return jsonify(convs), 200
    finally:
        _run(client.close())


@app.route("/api/conversations", methods=["POST"])
@require_account
@api_error_handler
def create_conversation(acct):
    conv_id = str(uuid_lib.uuid4())

    client = _make_claude_client(acct)
    try:
        _run(client._ensure_conversation(conv_id))
    finally:
        _run(client.close())
    
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs = a.setdefault("pinned_conversations", [])
                if not any(c["conv_uuid"] == conv_id for c in convs):
                    convs.append({"conv_uuid": conv_id, "display_name": "",
                                  "pinned_at": _now()})
                break
    store.mutate(fn)

    log.info("Created conversation %s", conv_id[:8])
    return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201


@app.route("/api/conversations/<conv_id>", methods=["GET"])
@require_account
@api_error_handler
def get_conversation(acct, conv_id):
    client = _make_claude_client(acct)
    try:
        data = _run(client.get_conversation(conv_id))
        return jsonify(data), 200
    finally:
        _run(client.close())


@app.route("/api/conversations/<conv_id>", methods=["PUT"])
@require_account
@api_error_handler
def update_conversation(acct, conv_id):
    payload = request.json or {}

    client = _make_claude_client(acct)
    try:
        _run(client.update_conversation_settings(conv_id, payload))
    finally:
        _run(client.close())

    if (display_name := payload.get("name")) is not None:
        def fn(data):
            for a in data["accounts"]:
                if a["name"] == acct["name"]:
                    for c in a.get("pinned_conversations", []):
                        if c["conv_uuid"] == conv_id:
                            c["display_name"] = display_name
                            break
                    break
        store.mutate(fn)
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>/stop", methods=["POST"])
@require_account
@api_error_handler
def stop_response(acct, conv_id):
    _run(_make_claude_client(acct).stop_response(conv_id))
    return jsonify({"success": True})


# ── Messaging ─────────────────────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
@require_account
@api_error_handler
def send_message(acct, conv_id):
    data = request.json or {}
    payload = build_claude_payload(data)
    _log_message_send(acct["name"], conv_id, payload["model"],
                      len(payload.get("prompt", "")))

    def generate():
        for chunk in _sync_stream_claude(acct, conv_id, payload):
            yield chunk

    return Response(stream_with_context(generate()),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── File handling ─────────────────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>/upload", methods=["POST"])
@require_account
@api_error_handler
def upload_file(acct, conv_id):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f          = request.files["file"]
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"

    # Upload via Claude API
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        client = _make_claude_client(acct)
        try:
            _run(client._ensure_conversation(conv_id))
            file_uuid = _run(client.upload_file(conv_id, tmp_path))
        finally:
            _run(client.close())
    finally:
        os.unlink(tmp_path)

    _save_upload_meta(acct["name"], conv_id, file_uuid, fname, len(file_bytes), mime)
    log.info("Uploaded %s (%d bytes) → %s…", fname, len(file_bytes), file_uuid[:8])
    return jsonify({"file_uuid": file_uuid, "_upload_ok": True,
                    "_filename": fname, "_size": len(file_bytes),
                    "_mime": mime}), 200


@app.route("/api/conversations/<conv_id>/download", methods=["GET"])
@require_account
@api_error_handler
def download_file(acct, conv_id):
    file_path = request.args.get("path", "")
    if not file_path:
        return jsonify({"error": "Missing 'path' query parameter"}), 400

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        client = _make_claude_client(acct)
        try:
            local = _run(client.download_file(conv_id, file_path, dest=tmpdir))
        finally:
            _run(client.close())
        content = local.read_bytes()

    filename = file_path.split("/")[-1] or "download"

    # ?inline=1 -> serve for browser preview (no download prompt)
    inline = request.args.get("inline", "0") == "1"

    # Detect proper content-type from filename (fallback: octet-stream)
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content, status=200,
                    headers={"Content-Type": mime_type,
                             "Content-Disposition": disposition,
                             "X-Content-Type-Options": "nosniff"})


# ── Usage ─────────────────────────────────────────────────────────────────────

@app.route("/api/usage", methods=["GET"])
@require_account
def get_usage(acct):
    now_dt  = datetime.now(timezone.utc)
    cut_24h = (now_dt - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cut_1h  = (now_dt - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    data    = store.read()
    msg_log = next(
        (a.get("message_log", []) for a in data["accounts"]
         if a["name"] == acct["name"]), [])
    msgs_24h = [m for m in msg_log if m.get("sent_at", "") > cut_24h]
    msgs_1h  = [m for m in msg_log if m.get("sent_at", "") > cut_1h]

    by_model: dict = {}
    for m in msgs_24h:
        k = m.get("model", "")
        by_model[k] = by_model.get(k, 0) + 1
    by_model = dict(sorted(by_model.items(), key=lambda x: -x[1]))

    snap = _get_latest_quota(acct["name"])
    result = {
        "provider":    "claude",
        "quota":       snap,
        "local_stats": {
            "messages_24h": len(msgs_24h),
            "messages_1h":  len(msgs_1h),
            "by_model":     by_model,
        },
    }
    if snap and "windows" in snap:
        result["windows"] = snap["windows"]
        if "remaining" in snap:
            result["remaining"] = snap["remaining"]

    return jsonify(result)


@app.route("/api/usage/history", methods=["GET"])
@require_account
def usage_history(acct):
    limit = min(int(request.args.get("limit", 50)), 200)
    data  = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            snaps  = a.get("usage_snapshots", [])
            recent = list(reversed(snaps[-limit:]))
            return jsonify([{"data": s["snapshot"], "at": s["captured_at"]}
                             for s in recent])
    return jsonify([])


@app.route("/api/usage/messages", methods=["GET"])
@require_account
def usage_messages(acct):
    limit = min(int(request.args.get("limit", 100)), 500)
    data  = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            msgs = a.get("message_log", [])
            return jsonify(list(reversed(msgs[-limit:])))
    return jsonify([])


# ── Local conversation index ──────────────────────────────────────────────────

def _local_conv_list_response(acct):
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            convs = sorted(
                a.get("pinned_conversations", []),
                key=lambda c: c.get("pinned_at", ""),
                reverse=True,
            )
            return jsonify(convs[:200])
    return jsonify([])


@app.route("/api/local/conversations", methods=["GET"])
@require_account
def local_conv_list(acct):
    return _local_conv_list_response(acct)


@app.route("/api/local/conversations", methods=["POST"])
@require_account
def local_conv_pin(acct):
    req          = request.json or {}
    conv_uuid    = (req.get("conv_uuid") or "").strip()
    display_name = req.get("display_name", "")
    if not conv_uuid:
        return jsonify({"error": "conv_uuid required"}), 400

    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs    = a.setdefault("pinned_conversations", [])
                existing = next((c for c in convs if c["conv_uuid"] == conv_uuid), None)
                if existing:
                    if display_name:
                        existing["display_name"] = display_name
                    existing["pinned_at"] = _now()
                else:
                    convs.append({"conv_uuid": conv_uuid,
                                  "display_name": display_name,
                                  "pinned_at": _now()})
                break

    store.mutate(fn)
    return jsonify({"success": True}), 201


@app.route("/api/local/conversations/<conv_uuid>", methods=["DELETE"])
@require_account
def local_conv_unpin(acct, conv_uuid):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                a["pinned_conversations"] = [
                    c for c in a.get("pinned_conversations", [])
                    if c["conv_uuid"] != conv_uuid
                ]
                break
    store.mutate(fn)
    return jsonify({"success": True})


@app.route("/api/local/conversations/<conv_uuid>", methods=["PATCH"])
@require_account
def local_conv_rename(acct, conv_uuid):
    display_name = (request.json or {}).get("display_name", "")

    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                for c in a.get("pinned_conversations", []):
                    if c["conv_uuid"] == conv_uuid:
                        c["display_name"] = display_name
                        break
                break
    store.mutate(fn)
    return jsonify({"success": True})


# ── File upload metadata ──────────────────────────────────────────────────────

@app.route("/api/local/uploads/<conv_uuid>", methods=["GET"])
@require_account
def list_uploads(acct, conv_uuid):
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            uploads = sorted(
                [u for u in a.get("file_uploads", []) if u["conv_uuid"] == conv_uuid],
                key=lambda u: u.get("uploaded_at", ""),
            )
            return jsonify(uploads)
    return jsonify([])


# ── Settings (Claude only) ────────────────────────────────────────────────────

@app.route("/api/settings", methods=["PATCH"])
@require_account
@api_error_handler
def update_settings(acct):
    payload = request.json or {}
    client  = _make_claude_client(acct)
    try:
        _run(client.patch_settings(payload))
    finally:
        _run(client.close())
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("  ✦  Claude Console  v4  ✦")
    print(f"  Store:  {STORE_PATH}")
    print("  URL:    http://localhost:5000")
    print()
    app.run(debug=True, port=5000, threaded=True)