"""
Claude Console — Web UI Backend  v4
Powered by claude_webapi.

Run:  python app.py
Open: http://localhost:5000
Data: ./data/accounts.json
"""

import asyncio
import base64
import json
import logging
import os
import secrets
import sys
import threading
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, Response, jsonify, render_template, render_template_string,
    request, stream_with_context,
)
import requests as http_client

from claude_webapi import ClaudeClient
from oneminai_webapi import OneMinAIClient
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

CLAUDE_PROVIDER = "claude"
CHATWITHAI_PROVIDER = "chatwithai"
CHATWITHAI_API_BASE = "https://api.chatwithai.app"
CHATWITHAI_DEFAULT_MODEL = "claude-sonnet-4-6"
ONEMINAI_PROVIDER = "oneminai"
ONEMINAI_DEFAULT_MODEL = "gpt-4.1-nano"

# ═══════════════════════════════════════════════════════════════════════════════
# JSON Store
# ═══════════════════════════════════════════════════════════════════════════════

STORE_PATH = Path(__file__).parent / "data" / "accounts.json"
STORE_PATH.parent.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Model Management
# ═══════════════════════════════════════════════════════════════════════════════

CLAUDE_MODELS = [
    {"id": "claude-sonnet-4-6", "display_name": "Claude 4.6 Sonnet", "category": "text"},
    #{"id": "claude-opus-4-6", "display_name": "Claude 4.6 Opus", "category": "text"},
    {"id": "claude-haiku-4-5-20251001", "display_name": "Claude 4.5 Haiku", "category": "text"},
]

def _get_models_for_provider(provider: str) -> list[dict]:
    """Get available models based on provider."""
    if provider == CHATWITHAI_PROVIDER:
        try:
            return _chatwithai_fetch_models()
        except Exception:
            return _CHATWITHAI_MODEL_CACHE.get("models", [])
    elif provider == CLAUDE_PROVIDER:
        return CLAUDE_MODELS
    elif provider == ONEMINAI_PROVIDER:
        try:
            return _oneminai_fetch_models()
        except Exception:
            return _ONEMINAI_MODEL_CACHE.get("models", [])
    else:
        return []

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
    org = acct.get("organization_id") or None
    if not sk:
        raise ValueError(f"Account '{acct.get('name', '?')}' is missing session_key")
    client = ClaudeClient(sk, org)
    _run(client.init(timeout=60, auto_close=True, close_delay=120))
    return client

def _get_remote_conversation_id(acct: dict, local_conv_id: str) -> str | None:
    data = store.read()
    for a in data["accounts"]:
        if a["name"] != acct["name"]:
            continue
        for c in a.get("pinned_conversations", []):
            if c.get("conv_uuid") == local_conv_id:
                return c.get("remote_conversation_id") or c.get("conversation_id")
    return None


def _set_remote_conversation_id(acct: dict, local_conv_id: str, remote_conv_id: str):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs = a.setdefault("pinned_conversations", [])
                existing = next((c for c in convs if c.get("conv_uuid") == local_conv_id), None)
                if existing:
                    existing["remote_conversation_id"] = remote_conv_id
                else:
                    convs.append({"conv_uuid": local_conv_id, "remote_conversation_id": remote_conv_id, "display_name": "", "pinned_at": _now()})
                break
    store.mutate(fn)



def _chatwithai_headers() -> dict:
    return {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://chatwithai.app",
        "Referer": "https://chatwithai.app/chat/index",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        ),
        "X-Device-Id": str(uuid_lib.uuid4()),
    }


_CHATWITHAI_MODEL_CACHE: dict = {"fetched_at": 0.0, "models": []}


def _chatwithai_fetch_models() -> list[dict]:
    now_ts = datetime.now(timezone.utc).timestamp()
    if _CHATWITHAI_MODEL_CACHE["models"] and now_ts - _CHATWITHAI_MODEL_CACHE["fetched_at"] < 900:
        return _CHATWITHAI_MODEL_CACHE["models"]
    url = f"{CHATWITHAI_API_BASE}/api/v1/chatwithai/chats/models"
    resp = http_client.get(url, headers=_chatwithai_headers(), timeout=20)
    if resp.status_code != 200:
        return _CHATWITHAI_MODEL_CACHE["models"]
    payload = resp.json()
    models: list[dict] = []
    for vendor in payload.get("data", []) or []:
        for m in vendor.get("models", []) or []:
            mid = m.get("id") or m.get("slug")
            if not mid:
                continue
            models.append({
                "id": mid,
                "display_name": m.get("display_name") or mid,
                "vendor": vendor.get("display_name", ""),
                "vendor_slug": vendor.get("slug", ""),
                "category": m.get("category") or "text",
                "context_size": m.get("context_size"),
                "description": m.get("description", ""),
            })
    _CHATWITHAI_MODEL_CACHE["models"] = models
    _CHATWITHAI_MODEL_CACHE["fetched_at"] = now_ts
    return models

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
                timeout=3600
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

def _sync_stream_chatwithai(prompt: str, model: str, *, assistant_uuid: str):
    url = f"{CHATWITHAI_API_BASE}/api/v1/chatwithai/chats/anonymous/events"
    payload = {
        "message": prompt,
        "chat_id": None,
        "message_context": "default",
        "model": model,
    }

    text_accum: list[str] = []
    started = False
    message_uuid = assistant_uuid

    def emit(obj: dict):
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    def start_if_needed():
        nonlocal started
        if started:
            return None
        started = True
        return [
            emit({"type": "message_start", "message": {"uuid": message_uuid}}),
            emit({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ]

    resp = http_client.post(
        url,
        json=payload,
        headers=_chatwithai_headers(),
        stream=True,
        timeout=60,
    )
    if resp.status_code != 200:
        err = {"type": "error", "error": {"type": "api_error", "message": f"HTTP {resp.status_code}"}}
        yield emit(err)
        return

    # Use iter_content with decode_unicode=False to preserve raw bytes
    buffer = b""
    for chunk in resp.iter_content(chunk_size=1024, decode_unicode=False):
        if not chunk:
            continue
        
        buffer += chunk
        lines = buffer.split(b'\n')
        buffer = lines[-1]  # Keep incomplete line in buffer
        
        for line_bytes in lines[:-1]:
            try:
                line = line_bytes.decode('utf-8', errors='replace').strip()
            except UnicodeDecodeError:
                continue
                
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str:
                continue
            try:
                evt = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            evt_type = evt.get("event_type")
            evt_data = evt.get("data") or {}

            if evt_type == "message_created":
                message_uuid = evt_data.get("id") or message_uuid
                start_events = start_if_needed()
                if start_events:
                    for ev in start_events:
                        yield ev
                continue

            if evt_type == "ai_response_chunk":
                if not started:
                    start_events = start_if_needed()
                    if start_events:
                        for ev in start_events:
                            yield ev
                chunk_text = evt_data.get("chunk") or ""
                if chunk_text:
                    text_accum.append(chunk_text)
                    yield emit({
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": chunk_text},
                    })

    # Process any remaining data in buffer
    if buffer:
        try:
            line = buffer.decode('utf-8', errors='replace').strip()
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        evt = json.loads(data_str)
                        evt_type = evt.get("event_type")
                        if evt_type == "ai_response_chunk":
                            chunk_text = evt.get("data", {}).get("chunk") or ""
                            if chunk_text:
                                text_accum.append(chunk_text)
                                yield emit({
                                    "type": "content_block_delta",
                                    "index": 0,
                                    "delta": {"type": "text_delta", "text": chunk_text},
                                })
                    except json.JSONDecodeError:
                        pass
        except UnicodeDecodeError:
            pass

    if started:
        yield emit({"type": "content_block_stop", "index": 0})
        yield emit({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
        yield emit({"type": "message_stop"})




# ═══════════════════════════════════════════════════════════════════════════════
# 1min.AI helpers
# ═══════════════════════════════════════════════════════════════════════════════

_ONEMINAI_MODEL_CACHE: dict = {"fetched_at": 0.0, "models": []}


def _oneminai_fetch_models() -> list[dict]:
    now_ts = datetime.now(timezone.utc).timestamp()
    if _ONEMINAI_MODEL_CACHE["models"] and now_ts - _ONEMINAI_MODEL_CACHE["fetched_at"] < 900:
        return _ONEMINAI_MODEL_CACHE["models"]
    try:
        client = _make_oneminai_client_anon()
        raw = _run(client.list_models(feature="UNIFY_CHAT_WITH_AI"))
        models = [
            {
                "id":           m.get("modelId", ""),
                "display_name": m.get("name", m.get("modelId", "")),
                "provider":     m.get("provider", ""),
                "category":     "text",
            }
            for m in raw if m.get("modelId")
        ]
        _run(client.close())
        _ONEMINAI_MODEL_CACHE["models"]     = models
        _ONEMINAI_MODEL_CACHE["fetched_at"] = now_ts
        return models
    except Exception as exc:
        log.warning("1min.AI model fetch failed: %s", exc)
        return _ONEMINAI_MODEL_CACHE.get("models", [])


def _make_oneminai_client_anon() -> OneMinAIClient:
    """Temporary unauthenticated client for model catalog fetching."""
    return OneMinAIClient("")


def _make_oneminai_client(acct: dict) -> OneMinAIClient:
    key = acct.get("api_key") or acct.get("session_key", "")
    if not key:
        raise ValueError(f"1min.AI account '{acct.get('name','?')}' is missing api_key")
    return OneMinAIClient(key)


def _sync_stream_oneminai(acct: dict, conv_id: str, prompt: str, model: str,
                           *, human_uuid: str, asst_uuid: str):
    """
    Stream a 1min.AI chat response as Claude-compatible SSE events so the
    frontend can consume them without any changes.
    """
    import queue as _queue

    q: "_queue.Queue" = _queue.Queue()

    def emit(obj: dict) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    async def producer():
        client = _make_oneminai_client(acct)
        try:
            # Ensure the conversation exists server-side
            existing = await client._ensure_conversation(conv_id, prompt)
            actual_conv_id = existing or conv_id

            # Yield message_start so the frontend knows the UUID
            q.put(emit({"type": "message_start",
                         "message": {"uuid": asst_uuid, "model": model}}))
            q.put(emit({"type": "content_block_start", "index": 0,
                         "content_block": {"type": "text", "text": ""}}))

            async for chunk in await client.chat(
                prompt,
                stream          = True,
                model           = model,
                conversation_id = actual_conv_id,
            ):
                if chunk.text_delta:
                    q.put(emit({
                        "type":  "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": chunk.text_delta},
                    }))

            q.put(emit({"type": "content_block_stop", "index": 0}))
            q.put(emit({"type": "message_delta",
                         "delta": {"stop_reason": "end_turn"}}))
            q.put(emit({"type": "message_stop"}))
        except Exception as exc:
            q.put(emit({"type": "error",
                         "error": {"type": "api_error",
                                   "message": str(exc)}}))
        finally:
            await client.close()
            q.put(None)

    asyncio.run_coroutine_threadsafe(producer(), _loop)
    while True:
        item = q.get()
        if item is None:
            break
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


def _provider_name(acct: dict) -> str:
    return (acct.get("provider") or CLAUDE_PROVIDER).strip().lower()

def _normalize_provider(provider: str | None) -> str:
    prov = (provider or CLAUDE_PROVIDER).strip().lower()
    if prov in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER):
        return prov
    return CLAUDE_PROVIDER


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


def _get_local_conv_entry(acct_name: str, conv_id: str) -> dict | None:
    """Get a local conversation entry for ChatWithAI provider"""
    data = store.read()
    for acct in data.get("accounts", []):
        if acct["name"] == acct_name:
            # Check pinned conversations
            for conv in acct.get("pinned_conversations", []):
                if conv.get("conv_uuid") == conv_id:
                    return conv
            # Also check if there's a conversations list (for compatibility)
            for conv in acct.get("conversations", []):
                if conv.get("conv_uuid") == conv_id:
                    return conv
    return None



def _upsert_local_conv(acct_name: str, conv_id: str, updates: dict | None = None) -> dict:
    updates = updates or {}

    def fn(data):
        for a in data["accounts"]:
            if a["name"] != acct_name:
                continue
            convs = a.setdefault("pinned_conversations", [])
            existing = next((c for c in convs if c.get("conv_uuid") == conv_id), None)
            if not existing:
                existing = {
                    "conv_uuid": conv_id,
                    "display_name": "",
                    "created_at": _now(),
                    "updated_at": _now(),
                    "pinned_at": _now(),
                    "chat_messages": [],
                    "current_leaf_message_uuid": "00000000-0000-4000-8000-000000000000",
                    "provider": CHATWITHAI_PROVIDER,
                    "metadata": {}
                }
                convs.append(existing)
            
            # Apply updates
            existing.update(updates)
            if "updated_at" not in updates:
                existing["updated_at"] = _now()
            existing["pinned_at"] = existing.get("updated_at", _now())
            break

    store.mutate(fn)
    return _get_local_conv_entry(acct_name, conv_id) or {}


def _append_local_messages(
    acct_name: str,
    conv_id: str,
    human_msg: dict,
    asst_msg: dict,
    *,
    display_name: str | None = None,
):
    def fn(data):
        for a in data["accounts"]:
            if a["name"] != acct_name:
                continue
            convs = a.setdefault("pinned_conversations", [])
            conv = next((c for c in convs if c.get("conv_uuid") == conv_id), None)
            if not conv:
                conv = {
                    "conv_uuid": conv_id,
                    "display_name": display_name or "",
                    "created_at": _now(),
                    "updated_at": _now(),
                    "pinned_at": _now(),
                    "chat_messages": [],
                    "current_leaf_message_uuid": "00000000-0000-4000-8000-000000000000",
                    "settings": {},
                    "provider": CHATWITHAI_PROVIDER,
                }
                convs.append(conv)
            
            msgs = conv.setdefault("chat_messages", [])
            
            # Ensure proper UUID chain
            if not human_msg.get("parent_message_uuid"):
                if msgs:
                    human_msg["parent_message_uuid"] = msgs[-1]["uuid"]
                else:
                    human_msg["parent_message_uuid"] = "00000000-0000-4000-8000-000000000000"
            
            asst_msg["parent_message_uuid"] = human_msg["uuid"]
            
            # Add content structure if missing
            if "content" not in human_msg and "text" in human_msg:
                human_msg["content"] = [{"type": "text", "text": human_msg["text"]}]
            if "content" not in asst_msg and "text" in asst_msg:
                asst_msg["content"] = [{"type": "text", "text": asst_msg["text"]}]
            
            # Set indices
            human_msg["index"] = len(msgs)
            asst_msg["index"] = len(msgs) + 1
            
            msgs.append(human_msg)
            msgs.append(asst_msg)
            conv["current_leaf_message_uuid"] = asst_msg.get("uuid")
            if display_name and not conv.get("display_name"):
                conv["display_name"] = display_name
            conv["updated_at"] = _now()
            conv["pinned_at"] = conv["updated_at"]
            break

    store.mutate(fn)



def _account_to_public(a: dict) -> dict:
    provider = _provider_name(a)
    pub: dict = {
        "name":            a["name"],
        "provider":        provider,
        "active":          bool(a.get("is_active")),
        "created_at":      a.get("created_at", ""),
        "session_key":     a.get("session_key", "") if provider == CLAUDE_PROVIDER else "",
        "organization_id": a.get("organization_id", "") if provider == CLAUDE_PROVIDER else "",
        "api_key":         a.get("api_key", "")  if provider == ONEMINAI_PROVIDER else "",
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
        for entry in CLAUDE_ACCOUNTS:
            if len(entry) == 2:
                name, session_key = entry
                org_id = ""
            elif len(entry) == 3:
                name, org_id, session_key = entry
            else:
                log.warning("Skipping malformed Claude account seed: %r", entry)
                continue
            if not any(a["name"] == name for a in data["accounts"]):
                creds = {"session_key": session_key}
                if org_id:
                    creds["organization_id"] = org_id
                data["accounts"].append(_new_account(name, "claude", **creds))
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


@app.after_request
def _cors_for_extension(response):
    """Allow browser-extension popups and content scripts to reach local endpoints."""
    if request.path.startswith("/api/oauth/") or request.path == "/api/ping":
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/oauth/<path:subpath>", methods=["OPTIONS"])
def _oauth_preflight(subpath):
    """Handle CORS preflight for all /api/oauth/* routes."""
    return "", 204


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# Per-request account resolution (replaces single active-account model)
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_account(req) -> dict | None:
    """
    Resolve account per-request. Priority:
      1. X-Account-Name header
      2. account_name query param
      3. account_name in JSON body
      4. Server is_active fallback
    """
    name = req.headers.get("X-Account-Name", "").strip()
    
    if not name:
        name = req.args.get("account_name", "").strip()
    
    if not name and req.method in ("POST", "PUT", "PATCH"):
        if req.content_type and "application/json" in req.content_type:
            try:
                body = req.get_json(silent=True, force=False) or {}
                name = (body.get("account_name") or "").strip()
            except Exception:
                pass
    
    if name:
        acct = _get_account_by_name(name)
        if acct:
            return acct
        return None  # named but not found — don't silently fall through
    
    return _get_active_account()  # legacy fallback


def require_account(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        acct = _resolve_account(request)
        if not acct:
            name = (
                request.headers.get("X-Account-Name") or
                request.args.get("account_name") or ""
            ).strip()
            if name:
                return jsonify({"error": f"Account '{name}' not found"}), 404
            return jsonify({"error": "No active account configured"}), 401
        prov = _provider_name(acct)
        if prov == CLAUDE_PROVIDER and not acct.get("session_key"):
                return jsonify({"error": f"Account '{acct['name']}' is missing a session_key"}), 401
        if prov == ONEMINAI_PROVIDER and not acct.get("api_key"):
                return jsonify({"error": f"Account '{acct['name']}' is missing an api_key"}), 401
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
    provider = _provider_name(acct) if acct else None
    
    result = {
        "status": "ok",
        "store": str(STORE_PATH),
        "account": acct["name"] if acct else None,
        "provider": provider,
    }
    
    if provider:
        models = _get_models_for_provider(provider)
        result["models_available"] = len(models)
        if provider == CHATWITHAI_PROVIDER:
            result["default_model"] = CHATWITHAI_DEFAULT_MODEL
        elif provider == ONEMINAI_PROVIDER:
            result["default_model"] = ONEMINAI_DEFAULT_MODEL
        else:
            result["default_model"] = "claude-sonnet-4-6"
    
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Google OAuth
# ═══════════════════════════════════════════════════════════════════════════════
# Claude:    PKCE auth-code flow (v2). Extension intercepts claude.ai/oauth/callback
#            and POSTs the code back. ext-pending (v1) also supported so the
#            extension can poll before the popup opens.
# MiniApps:  Extension-driven GIS flow (both versions identical).

# In-memory state store: state -> {done, code/id_token/error, provider, pending_ext}
_oauth_states: dict = {}
_oauth_lock = threading.Lock()


# ── Claude OAuth (extension-driven flow) ─────────────────────────────────────

@app.route("/api/oauth/claude/owns-state")
def oauth_claude_owns_state():
    """Extension checks this before intercepting — prevents acting on non-Console callbacks."""
    state = request.args.get("state", "")
    with _oauth_lock:
        owned = state in _oauth_states and _oauth_states[state].get("provider") == "claude"
    return jsonify({"owned": owned})


@app.route("/api/oauth/claude/begin")
def oauth_claude_begin():
    state = secrets.token_hex(16)
    with _oauth_lock:
        _oauth_states[state] = {
            "done":        False,
            "provider":    "claude",
            "pending_ext": True,
        }
    return jsonify({"state": state})


@app.route("/api/oauth/claude/ext-pending")
def oauth_claude_ext_pending():
    """Content script polls this to learn whether a session is waiting for it.
    Marks the state as claimed immediately to prevent two tabs racing."""
    with _oauth_lock:
        for state, entry in _oauth_states.items():
            if (
                entry.get("provider") == "claude"
                and entry.get("pending_ext")
                and not entry["done"]
            ):
                entry["pending_ext"] = False  # claimed — only one tab handles it
                return jsonify({"state": state})
    return jsonify({"state": None})


@app.route("/api/oauth/claude/ext-callback", methods=["POST"])
def oauth_claude_ext_callback():
    """Receives the OAuth code relayed by the browser extension."""
    data  = request.get_json(silent=True) or {}
    code  = data.get("code")
    state = data.get("state")
    error = data.get("error")
    if not state:
        return jsonify({"ok": False, "error": "missing_state"}), 400
    with _oauth_lock:
        entry = _oauth_states.get(state)
    if not entry:
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry["done"]:
        return jsonify({"ok": True})  # already recorded (double-delivery)
    if code:
        entry.update({"code": code, "done": True, "pending_ext": False})
        return jsonify({"ok": True})
    entry.update({"error": error or "no_code", "done": True, "pending_ext": False})
    return jsonify({"ok": False, "error": error or "no_code"})


@app.route("/api/oauth/claude/status")
def oauth_claude_status():
    state = request.args.get("state", "")
    with _oauth_lock:
        entry = _oauth_states.get(state)
    if not entry:
        return jsonify({"error": "invalid_state"}), 400
    if not entry["done"]:
        return jsonify({"done": False})
    result: dict = {"done": True}
    if "code" in entry:
        result["code"] = entry["code"]
    if "error" in entry:
        result["error"] = entry["error"]
    with _oauth_lock:
        _oauth_states.pop(state, None)
    return jsonify(result)



# ── 1min.AI OAuth (Google access-token relay) ─────────────────────────────────
# The extension grabs the ya29.… token from the Google popup and POSTs it here.
# We then call client.oauth_login() to exchange it for a 1min.AI JWT.

@app.route("/api/oauth/oneminai/begin")
def oauth_oneminai_begin():
    state = secrets.token_hex(16)
    with _oauth_lock:
        _oauth_states[state] = {
            "done":        False,
            "provider":    "oneminai",
            "pending_ext": True,
        }
    return jsonify({"state": state})


@app.route("/api/oauth/oneminai/owns-state")
def oauth_oneminai_owns_state():
    state = request.args.get("state", "")
    with _oauth_lock:
        owned = state in _oauth_states and _oauth_states[state].get("provider") == "oneminai"
    return jsonify({"owned": owned})


@app.route("/api/oauth/oneminai/ext-pending")
def oauth_oneminai_ext_pending():
    with _oauth_lock:
        for state, entry in _oauth_states.items():
            if (
                entry.get("provider") == "oneminai"
                and entry.get("pending_ext")
                and not entry["done"]
            ):
                entry["pending_ext"] = False
                return jsonify({"state": state})
    return jsonify({"state": None})


@app.route("/api/oauth/oneminai/ext-callback", methods=["POST"])
def oauth_oneminai_ext_callback():
    """
    Extension POSTs the Google OAuth access token (ya29.…) here.
    We exchange it for a 1min.AI JWT and store the api_key.
    """
    data         = request.get_json(silent=True) or {}
    oauth_token  = data.get("oauth_token") or data.get("access_token") or data.get("token")
    state        = data.get("state")
    error        = data.get("error")

    if not state:
        return jsonify({"ok": False, "error": "missing_state"}), 400
    with _oauth_lock:
        entry = _oauth_states.get(state)
    if not entry:
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry["done"]:
        return jsonify({"ok": True})
    if error:
        entry.update({"error": error, "done": True, "pending_ext": False})
        return jsonify({"ok": False, "error": error})
    if not oauth_token:
        entry.update({"error": "no_token", "done": True})
        return jsonify({"ok": False, "error": "no_token"}), 400

    # Exchange Google token → 1min.AI JWT
    try:
        tmp_client = OneMinAIClient()
        user       = _run(tmp_client.oauth_login(oauth_token))
        api_key    = tmp_client._api_key
        _run(tmp_client.close())
        entry.update({
            "api_key":  api_key,
            "email":    user.email,
            "team_id":  user.team_id,
            "done":     True,
            "pending_ext": False,
        })
        log.info("1min.AI OAuth success: %s", user.email)
        return jsonify({"ok": True, "email": user.email})
    except Exception as exc:
        log.warning("1min.AI OAuth exchange failed: %s", exc)
        entry.update({"error": str(exc), "done": True, "pending_ext": False})
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/oauth/oneminai/status")
def oauth_oneminai_status():
    state = request.args.get("state", "")
    with _oauth_lock:
        entry = _oauth_states.get(state)
    if not entry:
        return jsonify({"error": "invalid_state"}), 400
    if not entry["done"]:
        return jsonify({"done": False})
    result: dict = {"done": True}
    if "api_key" in entry:
        result["api_key"] = entry["api_key"]
        result["email"]   = entry.get("email", "")
    if "error" in entry:
        result["error"] = entry["error"]
    with _oauth_lock:
        _oauth_states.pop(state, None)
    return jsonify(result)

@app.route("/api/models", methods=["GET"])
@require_account
def get_models(acct):
    """Get models for the account resolved from this request's context."""
    provider = _provider_name(acct)
    models   = _get_models_for_provider(provider)
    return jsonify({
        "provider":      provider,
        "account":       acct["name"],
        "models":        models,
        "default_model": (
            CHATWITHAI_DEFAULT_MODEL 
            if provider == CHATWITHAI_PROVIDER 
            else "claude-sonnet-4-6"
        ),
    })


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/c/<path:conv_id>")
def index(conv_id=None):
    return render_template("index.html")


# ── Accounts ──────────────────────────────────────────────────────────────────

@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    data = store.read()
    accounts = data["accounts"]
    active = next((a["name"] for a in accounts if a.get("is_active")), None)

    account_list = []
    for a in sorted(accounts, key=lambda x: (
        0 if _normalize_provider(x.get("provider")) == CLAUDE_PROVIDER else 1,
        x.get("name", "").lower(),
    )):
        pub = _account_to_public(a)
        provider = _provider_name(a)

        # Attach models directly — no per-request account resolution needed
        if provider == CHATWITHAI_PROVIDER:
            try:
                models = _chatwithai_fetch_models()
            except Exception:
                models = _CHATWITHAI_MODEL_CACHE.get("models", [])
        else:
            models = CLAUDE_MODELS

        pub["models"] = models
        pub["default_model"] = (
            CHATWITHAI_DEFAULT_MODEL
            if provider == CHATWITHAI_PROVIDER
            else "claude-sonnet-4-6"
        )
        pub["provider_info"] = {
            "type":               provider,
            "supports_files":     provider in (CLAUDE_PROVIDER, ONEMINAI_PROVIDER),
            "supports_artifacts": provider == CLAUDE_PROVIDER,
            "supports_tools":     provider == CLAUDE_PROVIDER,
            "supports_thinking":  provider == CLAUDE_PROVIDER,
            "supports_branching": provider == CLAUDE_PROVIDER,
            "supports_web_search": provider == ONEMINAI_PROVIDER,
            "supports_image_gen":  provider == ONEMINAI_PROVIDER,
        }
        account_list.append(pub)

    return jsonify({
        "accounts": account_list,
        "active":   active,
    })

@app.route("/api/accounts", methods=["POST"])
def add_account():
    req  = request.json or {}
    name = (req.get("name") or "").strip()
    provider = _normalize_provider(req.get("provider"))
    sk   = (req.get("session_key")     or "").strip()
    org  = (req.get("organization_id") or "").strip()
    claude_code = (req.get("claude_code") or "").strip()
    arkose_session_token = (req.get("arkose_session_token") or "").strip() or None
    setup_username = (req.get("setup_username") or "").strip()
    setup_password = (req.get("setup_password") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    existing_account = _get_account_by_name(name)

    boot_session_key    = sk
    boot_org            = org
    boot_last_auth_hash = None

    oneminai_api_key = (req.get("api_key") or "").strip()

    if provider == CLAUDE_PROVIDER and not boot_session_key and not existing_account:
        if claude_code:
            auth_client = _run(
                ClaudeClient.from_google_code(
                    claude_code,
                    arkose_session_token=arkose_session_token,
                    organization_id=org or None,
                )
            )
            boot_session_key = getattr(auth_client, "_session_key", "")
            boot_org = getattr(auth_client, "_organization_id", None) or org
            _run(auth_client.close())
        else:
            return jsonify({"error": "session_key or claude_code is required"}), 400

    active_name = None

    def fn(data):
        nonlocal active_name
        existing = next((a for a in data["accounts"] if a["name"] == name), None)
        if existing:
            existing.update({"provider": provider})
            if provider == CLAUDE_PROVIDER:
                if boot_session_key:
                    existing["session_key"] = boot_session_key
                if boot_org:
                    existing["organization_id"] = boot_org
                existing.pop("tool_slug", None)
            elif provider == ONEMINAI_PROVIDER:
                if oneminai_api_key:
                    existing["api_key"] = oneminai_api_key
                existing.pop("session_key", None)
                existing.pop("organization_id", None)
            else:
                existing.pop("session_key", None)
                existing.pop("organization_id", None)
                existing.pop("tool_slug", None)
        else:
            creds = {}
            if provider == CLAUDE_PROVIDER:
                creds["session_key"] = boot_session_key
                if boot_org:
                    creds["organization_id"] = boot_org
            elif provider == ONEMINAI_PROVIDER:
                creds["api_key"] = oneminai_api_key
            data["accounts"].append(_new_account(name, provider, **creds))
        if req.get("activate") or len(data["accounts"]) == 1:
            _set_active_in_data(data, name)
        active_name = next(
            (a["name"] for a in data["accounts"] if a.get("is_active")), None)

    store.mutate(fn)
    log.info("Account saved: %s provider=%s active=%s", name, provider, active_name == name)
    return jsonify({"success": True, "name": name,
                    "active": active_name == name}), 201


@app.route("/api/accounts/<n>", methods=["DELETE"])
def delete_account(n):
    acct = _get_account_by_name(n)
    if not acct:
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
    provider = _provider_name(acct) if acct else CLAUDE_PROVIDER
    
    # Get available models for the provider
    models = _get_models_for_provider(provider) if acct else []
    if provider == CHATWITHAI_PROVIDER:
        default_model = CHATWITHAI_DEFAULT_MODEL
    elif provider == ONEMINAI_PROVIDER:
        default_model = ONEMINAI_DEFAULT_MODEL
    else:
        default_model = "claude-sonnet-4-6"
    
    return jsonify({
        "session_key_set": bool(acct and acct.get("session_key")) if provider == CLAUDE_PROVIDER else bool(acct),
        "organization_id": acct.get("organization_id", "") if acct and provider == CLAUDE_PROVIDER else "",
        "active_account": acct["name"] if acct else None,
        "provider": provider,
        "configured": bool(acct),
        "models": models,
        "default_model": default_model
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}
    acct = _get_active_account()
    name = (data.get("name") or (acct["name"] if acct else "default")).strip()
    provider = _normalize_provider(data.get("provider") or (acct.get("provider") if acct else None))
    sk   = (data.get("session_key") or "").strip()
    org  = (data.get("organization_id") or "").strip()

    def fn(store_data):
        existing = next((a for a in store_data["accounts"] if a["name"] == name), None)
        if existing:
            existing["provider"] = provider
            if provider == CLAUDE_PROVIDER:
                if sk:
                    existing["session_key"] = sk
                if org:
                    existing["organization_id"] = org
                existing.pop("tool_slug", None)
            else:
                existing.pop("session_key", None)
                existing.pop("organization_id", None)
                existing.pop("tool_slug", None)
        else:
            creds = {}
            if provider == CLAUDE_PROVIDER:
                creds["session_key"] = sk or ""
                if org:
                    creds["organization_id"] = org
            store_data["accounts"].append(_new_account(name, provider, **creds))
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
    provider = _provider_name(acct)
    if provider in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER):
        data = store.read()
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs = sorted(
                    a.get("pinned_conversations", []),
                    key=lambda c: c.get("updated_at", c.get("created_at", "")),
                    reverse=True,
                )
                return jsonify([
                    {
                        "uuid": c.get("conv_uuid"),
                        "name": c.get("display_name", ""),
                        "created_at": c.get("created_at", ""),
                        "updated_at": c.get("updated_at", ""),
                    }
                    for c in convs if c.get("conv_uuid")
                ]), 200
        return jsonify([]), 200
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
    provider = _provider_name(acct)
    
    if provider in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER):
        _upsert_local_conv(acct["name"], conv_id, {
            "display_name": "",
            "created_at": _now(),
            "updated_at": _now(),
            "provider": provider,
        })
        log.info("Created %s local conversation %s", provider, conv_id[:8])
        return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201

    client = _make_claude_client(acct)
    try:
        _run(client.ensure_conversation(conv_id))
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
    provider = _provider_name(acct)

    if provider in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER):
        # Get the local conversation
        conv = _get_local_conv_entry(acct["name"], conv_id)
        
        if not conv:
            # Return empty conversation structure for new conversations
            return jsonify({
                "uuid": conv_id,
                "name": "",
                "created_at": _now(),
                "updated_at": _now(),
                "chat_messages": [],
                "current_leaf_message_uuid": "00000000-0000-4000-8000-000000000000",
                "settings": {}
            }), 200
        
        # Ensure all messages have proper structure
        messages = conv.get("chat_messages", [])
        root_uuid = "00000000-0000-4000-8000-000000000000"
        
        # Fix message structure if needed
        for i, msg in enumerate(messages):
            # Ensure UUID exists
            if "uuid" not in msg:
                msg["uuid"] = str(uuid_lib.uuid4())
            
            # Ensure parent_message_uuid exists
            if "parent_message_uuid" not in msg:
                msg["parent_message_uuid"] = messages[i-1]["uuid"] if i > 0 else root_uuid
            
            # Ensure content structure exists
            if "content" not in msg:
                if "text" in msg:
                    msg["content"] = [{"type": "text", "text": msg["text"]}]
                else:
                    msg["content"] = [{"type": "text", "text": ""}]
            
            # Ensure index exists
            if "index" not in msg:
                msg["index"] = i
            
            # Ensure sender exists
            if "sender" not in msg:
                msg["sender"] = "human" if i % 2 == 0 else "assistant"
            
            # Ensure created_at exists
            if "created_at" not in msg:
                msg["created_at"] = conv.get("created_at", _now())
        
        # Determine current leaf
        current_leaf = conv.get("current_leaf_message_uuid")
        if not current_leaf or current_leaf == root_uuid:
            current_leaf = messages[-1]["uuid"] if messages else root_uuid
        
        # Return proper conversation structure
        return jsonify({
            "uuid": conv_id,
            "name": conv.get("display_name", ""),
            "created_at": conv.get("created_at", _now()),
            "updated_at": conv.get("updated_at", _now()),
            "chat_messages": messages,
            "current_leaf_message_uuid": current_leaf,
            "settings": conv.get("settings", {})
        }), 200
    
    # Claude provider logic remains the same
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
    provider = _provider_name(acct)
    
    if provider in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER):
        if (display_name := payload.get("name")) is not None:
            _upsert_local_conv(acct["name"], conv_id, {
                "display_name": display_name,
                "updated_at": _now()
            })
        return jsonify({"success": True})

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
    provider = _provider_name(acct)
    if provider == CHATWITHAI_PROVIDER:
        return jsonify({"error": "Stop not supported for ChatWithAI"}), 400  
    _run(_make_claude_client(acct).stop_response(conv_id))
    return jsonify({"success": True})


# ── Messaging ─────────────────────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
@require_account
@api_error_handler
def send_message(acct, conv_id):
    data = request.json or {}
    provider = _provider_name(acct)

    if provider == ONEMINAI_PROVIDER:
        prompt       = (data.get("prompt") or "").strip()
        model        = (data.get("model") or ONEMINAI_DEFAULT_MODEL).strip()
        parent_uuid  = data.get("parent_message_uuid", "00000000-0000-4000-8000-000000000000")
        human_uuid   = str(uuid_lib.uuid4())
        asst_uuid    = str(uuid_lib.uuid4())
        display_name = data.get("display_name") or (prompt[:30] if prompt else "")
        _log_message_send(acct["name"], conv_id, model, len(prompt))

        def generate_oneminai():
            for chunk in _sync_stream_oneminai(
                acct, conv_id, prompt, model,
                human_uuid=human_uuid,
                asst_uuid=asst_uuid,
            ):
                yield chunk

        return Response(
            stream_with_context(generate_oneminai()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if provider == CHATWITHAI_PROVIDER:
        prompt = (data.get("prompt") or "").strip()
        model = (data.get("model") or CHATWITHAI_DEFAULT_MODEL).strip()
        parent_uuid = data.get("parent_message_uuid", "00000000-0000-4000-8000-000000000000")
        human_uuid = str(uuid_lib.uuid4())
        asst_uuid = str(uuid_lib.uuid4())

        # Get conversation and build history
        conv_entry = _get_local_conv_entry(acct["name"], conv_id)
        
        # Build message chain based on parent_uuid
        history = []
        if conv_entry and parent_uuid != "00000000-0000-4000-8000-000000000000":
            all_msgs = conv_entry.get("chat_messages", [])
            msg_map = {m.get("uuid"): m for m in all_msgs if m.get("uuid")}
            
            # Build chain from parent backwards
            current = parent_uuid
            chain = []
            while current and current != "00000000-0000-4000-8000-000000000000":
                if current in msg_map:
                    chain.insert(0, msg_map[current])
                    current = msg_map[current].get("parent_message_uuid")
                else:
                    break
            history = chain

        # Build history text for API
        if history:
            history_text = "\n".join(
                f"{'Human' if m.get('sender') == 'human' else 'Assistant'}: {m.get('text', '')}"
                for m in history
            )
            full_prompt = f"{history_text}\nHuman: {prompt}"
        else:
            full_prompt = prompt

        display_name = data.get("display_name") or (prompt[:30] if prompt else "")
        _log_message_send(acct["name"], conv_id, model, len(prompt))

        text_parts: list[str] = []

        def generate():
            for chunk in _sync_stream_chatwithai(full_prompt, model, assistant_uuid=asst_uuid):
                # Collect text deltas
                try:
                    line = chunk.decode("utf-8", errors="replace").strip()
                    for part in line.splitlines():
                        if not part.startswith("data:"):
                            continue
                        js = part[5:].strip()
                        if not js:
                            continue
                        evt = json.loads(js)
                        if evt.get("type") == "content_block_delta":
                            text_parts.append(evt.get("delta", {}).get("text", ""))
                except Exception:
                    pass
                yield chunk

            # Persist messages with proper structure
            full_response = "".join(text_parts)
            human_msg = {
                "uuid": human_uuid,
                "sender": "human",
                "text": prompt,
                "content": [{"type": "text", "text": prompt}],
                "parent_message_uuid": parent_uuid,
                "created_at": _now(),
            }
            asst_msg = {
                "uuid": asst_uuid,
                "sender": "assistant",
                "text": full_response,
                "content": [{"type": "text", "text": full_response}],
                "parent_message_uuid": human_uuid,
                "model": model,
                "created_at": _now(),
            }
            _append_local_messages(acct["name"], conv_id, human_msg, asst_msg,
                                   display_name=display_name)

        return Response(stream_with_context(generate()),
                        content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

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
    provider = _provider_name(acct)
    
    if provider == CHATWITHAI_PROVIDER:
        return jsonify({"error": "File uploads not supported for ChatWithAI"}), 400
    if provider == ONEMINAI_PROVIDER:
        # 1min.AI uploads go via the Asset API — use /api/oneminai/upload
        return jsonify({"error": "Use /api/oneminai/upload for 1min.AI file uploads"}), 400
    
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f          = request.files["file"]
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        client = _make_claude_client(acct)
        try:
            _run(client.ensure_conversation(conv_id))
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
    inline   = request.args.get("inline", "0") == "1"

    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content, status=200,
                    headers={"Content-Type": mime_type,
                             "Content-Disposition": disposition,
                             "X-Content-Type-Options": "nosniff"})




# ── 1min.AI Asset Upload ──────────────────────────────────────────────────────

@app.route("/api/oneminai/upload", methods=["POST"])
@require_account
@api_error_handler
def oneminai_upload_asset(acct):
    """Upload a file to the 1min.AI Asset API and return asset_key + file_id."""
    provider = _provider_name(acct)
    if provider != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f          = request.files["file"]
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"

    client = _make_oneminai_client(acct)
    try:
        asset = _run(client.upload_asset(
            data=file_bytes, filename=fname, mime_type=mime
        ))
        _run(client.close())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    _save_upload_meta(acct["name"], "oneminai", asset.file_id, fname, len(file_bytes), mime)
    log.info("1min.AI asset uploaded: %s → key=%s", fname, asset.asset_key[:16])
    return jsonify({
        "asset_key": asset.asset_key,
        "file_id":   asset.file_id,
        "filename":  fname,
        "size":      len(file_bytes),
        "mime":      mime,
        "_upload_ok": True,
    }), 200

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


@app.route("/api/local/conversations", methods=["GET"])
@require_account
def local_conv_list(acct):
    """Returns pinned/local conversations for the resolved account."""
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            convs = sorted(
                a.get("pinned_conversations", []),
                key=lambda c: c.get("pinned_at", c.get("updated_at", "")),
                reverse=True,
            )
            return jsonify(convs[:200])
    return jsonify([])


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