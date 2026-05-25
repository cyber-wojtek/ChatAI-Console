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
import re
import secrets
import sys
import threading
import atexit
import signal
import subprocess
import shutil
import uuid as uuid_lib
from datetime import datetime, time, timedelta, timezone
from functools import wraps
from pathlib import Path
import argparse
import hypercorn.asyncio
import hypercorn.config
import multiprocessing
from bs4 import BeautifulSoup
import redis
import time as _time
import argparse
from hypercorn.config import Config
from hypercorn.asyncio import serve


from quart import (
    Quart, Response, jsonify, render_template, render_template_string,
    request, stream_with_context,
)

import httpx as http_client

from claude_webapi import ClaudeClient
from flowith_webapi import FlowithClient
from oneminai_webapi import OneMinAIClient

# Alias: older call-sites used stop_conversation_response; the library
# exposes stop_response — add a forward-compatible shim at import time.
if not hasattr(ClaudeClient, "stop_conversation_response"):
    ClaudeClient.stop_conversation_response = ClaudeClient.stop_response  # type: ignore[attr-defined]
from oneminai_webapi.exceptions import CloudflareError as OneMinAICFError
from claude_webapi.constants import CLAUDE_BASE_URL
from claude_webapi.exceptions import (
    APIError, AuthenticationError, QuotaExceededError,
)
from urllib.parse import urlparse, urljoin, quote, unquote

# Shared session for ChatWithAI — connection-pooled, keep-alive enabled.
_CHATWITHAI_SESSION = None  # lazy-initialised in _get_chatwithai_client()


def _get_chatwithai_client() -> "http_client.Client":
    global _CHATWITHAI_SESSION
    if _CHATWITHAI_SESSION is None:
        s = http_client.Client()
        _CHATWITHAI_SESSION = s
    return _CHATWITHAI_SESSION


# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chatai-console")

CLAUDE_PROVIDER = "claude"
CHATWITHAI_PROVIDER = "chatwithai"
CHATWITHAI_API_BASE = "https://api.chatwithai.app"
CHATWITHAI_DEFAULT_MODEL = "claude-sonnet-4-6"
ONEMINAI_PROVIDER = "oneminai"
FLOWITH_PROVIDER = "flowith"
FLOWITH_DEFAULT_MODEL = "gpt-4.1-nano"
ONEMINAI_DEFAULT_MODEL = "gpt-4.1-nano"

# Canonical root UUID used across all providers for the parent chain root.
ROOT_UUID = "00000000-0000-4000-8000-000000000000"

# ── Rate-limit / polling configuration ────────────────────────────────────
# These can be overridden at runtime via /api/settings/polling (PATCH).
_POLLING_CFG = {
    "auto_poll_credits":   True,   # poll credits/quota in the background
    "poll_interval_sec":   90,     # seconds between background polls
    "stagger_delay_sec":   10,    # seconds between per-account requests
    "request_timeout_sec": 30,     # per-request timeout for usage calls
}

# ═══════════════════════════════════════════════════════════════════════════════
# JSON Store
# ═══════════════════════════════════════════════════════════════════════════════

STORE_PATH = Path(__file__).parent / "data" / "accounts.json"
STORE_PATH.parent.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Model Management
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_json() -> dict:
    """Parse JSON body safely, handling non-ASCII (UTF-8) payloads."""
    raw = await request.get_data()          # raw bytes, no encoding assumption
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}

CLAUDE_MODELS = [
    {"id": "claude-sonnet-4-6", "display_name": "Claude 4.6 Sonnet", "category": "text"},
    {"id": "claude-opus-4-6", "display_name": "Claude 4.6 Opus 💰", "category": "text"},
    {"id": "claude-haiku-4-5-20251001", "display_name": "Claude 4.5 Haiku", "category": "text"},
]

async def _get_models_for_provider(provider: str) -> list[dict]:
    """Get available models based on provider."""
    if provider == CHATWITHAI_PROVIDER:
        try:
            return await _chatwithai_fetch_models()
        except Exception:
            return _CHATWITHAI_MODEL_CACHE.get("models", [])
    elif provider == CLAUDE_PROVIDER:
        return CLAUDE_MODELS
    elif provider == ONEMINAI_PROVIDER:
        try:
            return await _oneminai_fetch_models()
        except Exception:
            return _ONEMINAI_MODEL_CACHE.get("models", [])
    elif provider == FLOWITH_PROVIDER:
        try:
            return await _flowith_fetch_models()
        except Exception:
            return _FLOWITH_MODEL_CACHE.get("models", [])
    else:
        return []

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


STORE_KEY = "chatai:store"
STORE_LOCK_KEY = "chatai:store_lock"

STORE_KEY = "chatai:store"
STORE_LOCK_KEY = "chatai:store_lock"

# ── Redis auto-start ──────────────────────────────────────────────────────────

_redis_proc = None

def _start_redis():
    global _redis_proc
    if not shutil.which("redis-server"):
        log.warning("redis-server not found — install it or set REDIS_URL manually")
        return
    _redis_proc = subprocess.Popen(
        ["redis-server", "--daemonize", "no", "--loglevel", "warning"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    r = redis.Redis()
    for _ in range(50):
        try:
            r.ping()
            log.info("Redis started (pid %d)", _redis_proc.pid)
            return
        except Exception:
            _time.sleep(0.1)
    log.warning("Redis didn't respond in time")

@atexit.register
def _stop_redis():
    if _redis_proc:
        _redis_proc.terminate()
        try:
            _redis_proc.wait(timeout=5)
        except Exception:
            _redis_proc.kill()
        log.info("Redis stopped")

#_start_redis()

# ── RedisStore ────────────────────────────────────────────────────────────────

class RedisStore:
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._r = redis.Redis.from_url(redis_url, decode_responses=True)
        self._local_lock = threading.Lock()
        self._ensure_initialized()
        log.info("Redis store ready  %s", redis_url)

    def _ensure_initialized(self):
        if not self._r.exists(STORE_KEY):
            self._r.set(STORE_KEY, json.dumps({"accounts": []}))

    def read(self) -> dict:
        raw = self._r.get(STORE_KEY)
        if not raw:
            return {"accounts": []}
        data = json.loads(raw)
        data.setdefault("accounts", [])
        return data

    def mutate(self, fn):
        with self._local_lock:
            with self._r.lock(STORE_LOCK_KEY, timeout=15, blocking_timeout=15):
                raw = self._r.get(STORE_KEY)
                data = json.loads(raw) if raw else {"accounts": []}
                data.setdefault("accounts", [])
                fn(data)
                self._r.set(STORE_KEY, json.dumps(data, ensure_ascii=False))
                
    def migrate_from_json(self, json_store: "JSONStore"):
        data = json_store.read()
        with self._local_lock:
            with self._r.lock(STORE_LOCK_KEY, timeout=15, blocking_timeout=15):
                self._r.set(STORE_KEY, json.dumps(data, ensure_ascii=False))

class JSONStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._ensure_file()
        self._data: dict = {}
        with open(self.path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def _ensure_file(self):
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"accounts": []}))

    def read(self) -> dict:
        with self._lock:
            return self._data

    def mutate(self, fn):
        with self._lock:
            data = self._data
            fn(data)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save()
                
    def save(self):
        with self._lock:
            log.info("Saving JSON store to %s", self.path)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                
    def migrate_from_redis(self, redis_store: RedisStore):
        data = redis_store.read()
        with self._lock:
            self._data = data
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

#REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
store = JSONStore(path=Path("data/store.json"))  
#redis_ = RedisStore(redis_url=REDIS_URL)
#store.migrate_from_redis(redis_)  # one-time migration from Redis to JSON file
#store = RedisStore(redis_url=REDIS_URL)

# ══════════════════════════════════════════════════════════════════════════════
# Claude client + streaming
# ═══════════════════════════════════════════════════════════════════════════════

async def _make_claude_client(acct: dict) -> ClaudeClient:
    sk  = acct.get("session_key", "")
    org = acct.get("organization_id") or None
    if not sk:
        raise ValueError(f"Account '{acct.get('name', '?')}' is missing session_key")
    client = ClaudeClient(sk, org)
    await client.init(timeout=60, auto_close=True, close_delay=120)
    return client

async def _fetch_claude_usage(acct: dict) -> dict | None:
    """Fetch real usage data from Claude's account/usage endpoint."""
    client = await _make_claude_client(acct)
    try:
        raw = await client._get(f"{CLAUDE_BASE_URL}/api/organizations/{client._organization_id}/usage")
        await client.close()
        
        # Normalize to a consistent windows shape
        # The endpoint returns named keys like "five_hour", "seven_day" etc.
        # We normalize them to the short keys used everywhere else ("5h", "7d")
        KEY_MAP = {
            "five_hour":   "5h",
            "seven_day":   "7d",
            "one_hour":    "1h",
            "one_day":     "1d",
            "thirty_day":  "30d",
        }
        windows = {}
        for raw_key, data in raw.items():
            if not isinstance(data, dict):
                continue
            short_key = KEY_MAP.get(raw_key, raw_key)
            util = data.get("utilization", 0) or 0
            resets_at_str = data.get("resets_at")
            resets_at_ts = None
            if resets_at_str:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
                    resets_at_ts = int(dt.timestamp())
                except Exception:
                    pass
            
            util /= 100.0 # Normalize
            
            # Determine status from utilization
            if util >= 1.0:
                status = "exceeded_limit"
            elif util >= 0.9:
                status = "approaching_limit"
            else:
                status = "within_limit"
            windows[short_key] = {
                "utilization": util,
                "status":      status,
                "resets_at":   resets_at_ts,
            }
        
        return {"windows": windows, "type": None, "_raw": raw}
    except Exception as exc:
        log.warning("Claude usage fetch for '%s': %s", acct.get("name","?"), exc)
        try: await client.close()
        except Exception: pass
        return None

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


async def _chatwithai_fetch_models() -> list[dict]:
    now_ts = datetime.now(timezone.utc).timestamp()
    if _CHATWITHAI_MODEL_CACHE["models"] and now_ts - _CHATWITHAI_MODEL_CACHE["fetched_at"] < 900:
        return _CHATWITHAI_MODEL_CACHE["models"]
    url = f"{CHATWITHAI_API_BASE}/api/v1/chatwithai/chats/models"
    resp = _get_chatwithai_client().get(url, headers=_chatwithai_headers(), timeout=20)
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
    q = _queue.Queue()

    prompt      = payload.get("prompt", "")
    model       = payload.get("model", "claude-sonnet-4-6")
    parent_uuid = payload.get("parent_message_uuid",
                               "00000000-0000-4000-8000-000000000000")
    file_uuids  = payload.get("files", [])
    style_raw   = (payload.get("personalized_styles") or [None])[0]

    def emit(obj: dict) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    async def producer():
        client = None
        try:
            client = ClaudeClient(
                acct["session_key"],
                acct.get("organization_id") or None,
            )
            await client.init(timeout=60, auto_close=False)

            chat = client.start_chat(
                model    = model,
                metadata = {
                    "conversation_id":     conv_id,
                    "parent_message_uuid": parent_uuid,
                },
                style = style_raw,
            )

            async for chunk in chat.send_message_stream(
                prompt,
                files = file_uuids or None,
            ):
                # The library now yields raw_event for every SSE event.
                # Forward it directly — the frontend handles all Claude SSE types.
                if chunk.raw_event:
                    q.put(emit(chunk.raw_event))

        except QuotaExceededError as exc:
            q.put(emit({"type": "error", "error": {
                "type":    "rate_limit_error",
                "message": str(exc),
            }}))
        except AuthenticationError as exc:
            q.put(emit({"type": "error", "error": {
                "type":    "authentication_error",
                "message": str(exc),
            }}))
        except Exception as exc:
            log.exception("Claude stream error for conv %s", conv_id[:8])
            q.put(emit({"type": "error", "error": {
                "type":    "api_error",
                "message": str(exc),
            }}))
        finally:
            if client:
                try:
                    await client.close()
                except Exception:
                    pass
            q.put(None)

    asyncio.run_coroutine_threadsafe(producer(), _loop)

    while True:
        item = q.get()
        if item is None:
            break
        yield item

def _sync_stream_oneminai(acct, conv_id, prompt, model, *, human_uuid, asst_uuid,
                           file_uuids=None, web_search=False):
    import queue as _queue
    q = _queue.Queue()

    def emit(obj: dict) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    async def producer():
        client = None
        try:
            client = await _make_oneminai_client(acct)
            # Ensure team_id is resolved before streaming
            await client._get_team_id()
            q.put(emit({"type": "message_start", "message": {"uuid": asst_uuid, "model": model}}))
            q.put(emit({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}))
            async for chunk in await client.chat(
                prompt, stream=True, model=model,
                conversation_id=conv_id, files=file_uuids or [], web_search=web_search,
            ):
                if chunk.text_delta:
                    q.put(emit({"type": "content_block_delta", "index": 0,
                                "delta": {"type": "text_delta", "text": chunk.text_delta}}))
            q.put(emit({"type": "content_block_stop", "index": 0}))
            q.put(emit({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}))
            q.put(emit({"type": "message_stop"}))
        except OneMinAICFError as exc:
            state = secrets.token_hex(16)
            def _store_cf(d):
                d.setdefault("_cf_pending", {})[state] = {
                    "account_name": acct.get("name", ""),
                    "done": False,
                    "cf_clearance": None,
                }
            store.mutate(_store_cf)
            
            log.warning("1min.AI Cloudflare challenge: %s  state=%s", exc.challenge_type, state)
            q.put(emit({
                "type":           "cloudflare_challenge",
                "state":          state,
                "challenge_type": exc.challenge_type,
                "ray_id":         exc.ray_id,
                "url":            "https://app.1min.ai",
            }))
        except Exception as exc:
            q.put(emit({"type": "error", "error": {"type": "api_error", "message": str(exc)}}))
        finally:
            if client:
                try: await client.close()
                except Exception: pass
            q.put(None)

    asyncio.run_coroutine_threadsafe(producer(), _loop)
    while True:
        item = q.get()
        if item is None:
            break
        yield item

def _sync_stream_chatwithai_messages(
    messages: list[dict],
    model: str,
    *,
    timeout: int,
    assistant_uuid: str,
):
    """
    Stream a ChatWithAI response using a full messages array for history.
    messages = [{"role": "user"|"assistant", "content": str}, ...]
    """
    url = f"{CHATWITHAI_API_BASE}/api/v1/chatwithai/chats/anonymous/events"

    # Build the prompt by concatenating history in Human/Assistant format
    # OR pass the last message as `message` and history as `context`
    # The API only exposes `message` + `message_context`, so we encode
    # history into the message field using a clear delimiter.
    
    # Separate history from the final user turn
    history = messages[:-1]
    current_prompt = messages[-1]["content"] if messages else ""

    # Encode history as a system-style prefix the model will understand
    if history:
        history_lines = []
        for m in history:
            role_label = "Human" if m["role"] == "user" else "Assistant"
            history_lines.append(f"{role_label}: {m['content']}")
        history_text = "\n".join(history_lines)
        full_message = f"{history_text}\nHuman: {current_prompt}\nAssistant:"
    else:
        full_message = current_prompt

    payload = {
        "message": full_message,
        "chat_id": None,
        "message_context": "default",
        "model": model,
    }

    _TERMINAL_EVENTS = frozenset({
        "conversation_complete",
        "ai_response_complete",
        "stream_end",
        "done",
    })

    text_accum: list[str] = []
    started = False
    message_uuid = assistant_uuid

    def emit(obj: dict) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    def _start_blocks():
        nonlocal started
        if started:
            return
        started = True
        yield emit({"type": "message_start", "message": {"uuid": message_uuid}})
        yield emit({"type": "content_block_start", "index": 0,
                    "content_block": {"type": "text", "text": ""}})

    resp = None
    try:
        with _get_chatwithai_client().stream(
            "POST",
            url,
            json=payload,
            headers=_chatwithai_headers(),
            timeout=(10, timeout),
        ) as resp:
            if resp.status_code != 200:
                err = {"type": "error",
                    "error": {"type": "api_error",
                                "message": f"HTTP {resp.status_code}"}}
                yield emit(err)
                return

            buffer = b""
            done = False

            for raw_chunk in resp.iter_bytes(chunk_size=256):
                if not raw_chunk:
                    continue

                buffer += raw_chunk
                *lines, buffer = buffer.split(b"\n")

                for line_bytes in lines:
                    if not line_bytes or not line_bytes.startswith(b"data:"):
                        continue

                    try:
                        line = line_bytes.decode("utf-8", errors="replace")
                    except Exception:
                        continue

                    data_str = line[5:].strip()
                    if not data_str:
                        continue

                    try:
                        evt = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    evt_type = evt.get("event_type", "")
                    evt_data = evt.get("data") or {}

                    if evt_type in _TERMINAL_EVENTS:
                        done = True
                        break

                    if evt_type == "message_created":
                        _new_uuid = evt_data.get("id")
                        if _new_uuid:
                            message_uuid = _new_uuid
                        for block in _start_blocks():
                            yield block
                        continue

                    if evt_type == "ai_response_chunk":
                        for block in _start_blocks():
                            yield block
                        chunk_text = evt_data.get("chunk") or ""
                        if chunk_text:
                            text_accum.append(chunk_text)
                            yield emit({
                                "type": "content_block_delta",
                                "index": 0,
                                "delta": {"type": "text_delta", "text": chunk_text},
                            })

                if done:
                    break

        # flush leftover buffer
        if buffer and not done:
            try:
                line = buffer.decode("utf-8", errors="replace").strip()
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str:
                        try:
                            evt = json.loads(data_str)
                            if evt.get("event_type") == "ai_response_chunk":
                                chunk_text = evt.get("data", {}).get("chunk") or ""
                                if chunk_text:
                                    text_accum.append(chunk_text)
                                    for block in _start_blocks():
                                        yield block
                                    yield emit({
                                        "type": "content_block_delta",
                                        "index": 0,
                                        "delta": {"type": "text_delta", "text": chunk_text},
                                    })
                        except json.JSONDecodeError:
                            pass
            except UnicodeDecodeError:
                pass

    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    if started:
        yield emit({"type": "content_block_stop", "index": 0})
        yield emit({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
        yield emit({"type": "message_stop"})

# ═══════════════════════════════════════════════════════════════════════════════
# 1min.AI — everything goes through OneMinAIClient (oneminai_webapi module)
# ═══════════════════════════════════════════════════════════════════════════════

_ONEMINAI_MODEL_CACHE: dict = {"fetched_at": 0.0, "models": []}


async def _oneminai_fetch_models() -> list[dict]:
    from datetime import datetime, timezone
    now_ts = datetime.now(timezone.utc).timestamp()
    if _ONEMINAI_MODEL_CACHE["models"] and now_ts - _ONEMINAI_MODEL_CACHE["fetched_at"] < 900:
        return _ONEMINAI_MODEL_CACHE["models"]
    try:
        client = OneMinAIClient()          # anonymous — only needs team after login
        # list_models works without auth for the public catalog
        raw    = await client.list_models(feature="UNIFY_CHAT_WITH_AI")
        await client.close()
        models = [
            {
                "id":           m.get("modelId", ""),
                "display_name": m.get("name") or m.get("modelId", ""),
                "provider":     m.get("provider", ""),
                "category":     m.get("category", "text"),
                "context_size": m.get("contextSize"),
                "description":  m.get("description", ""),
            }
            for m in (raw or [])
            if m.get("modelId") and str(m.get("modelId")).strip()
        ]
        _ONEMINAI_MODEL_CACHE["models"]     = models
        _ONEMINAI_MODEL_CACHE["fetched_at"] = now_ts
        return models
    except Exception as exc:
        log.warning("1min.AI model fetch failed: %s", exc)
        return _ONEMINAI_MODEL_CACHE.get("models", [])


async def _make_oneminai_client(acct: dict) -> OneMinAIClient:
    """Return an authenticated OneMinAIClient from a stored account dict."""
    key     = acct.get("api_key") or acct.get("session_key", "")
    team_id = acct.get("team_id", "")
    if not key:
        raise ValueError(f"1min.AI account '{acct.get('name','?')}' is missing api_key")
    cf      = acct.get("cf_clearance")
    ua      = acct.get("user_agent")
    client  = OneMinAIClient(
        api_key      = key,
        cf_clearance = cf or None,
        user_agent   = ua or None,
    )
    if team_id:
        client._team_id = team_id   # skip the /users round-trip
    return client

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
    if prov in (CHATWITHAI_PROVIDER, ONEMINAI_PROVIDER, FLOWITH_PROVIDER):
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
            
            # Ensure proper UUID chain.
            # If caller already set parent_message_uuid (edit/branch), keep it.
            # Otherwise default to last message in chain.
            if not human_msg.get("parent_message_uuid"):
                if msgs:
                    human_msg["parent_message_uuid"] = msgs[-1]["uuid"]
                else:
                    human_msg["parent_message_uuid"] = "00000000-0000-4000-8000-000000000000"

            # Assistant always follows human
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
        "api_key":         a.get("api_key", "")    if provider in (ONEMINAI_PROVIDER, FLOWITH_PROVIDER) else "",
        "team_id":         a.get("team_id", "")    if provider == ONEMINAI_PROVIDER else "",
        "user_id":         a.get("user_id", "")      if provider == FLOWITH_PROVIDER else "",
        "refresh_token":   a.get("refresh_token", "") if provider == FLOWITH_PROVIDER else "",
    }
    return pub

_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True, name="async-loop")
_loop_thread.start()

def _seed_from_env():
    try:
        from keys import CLAUDE_ACCOUNTS
    except ImportError:
        try:
            from keys import ACCOUNTS as CLAUDE_ACCOUNTS
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

async def _warm_model_caches():
    """Fetch models for all configured providers in background — called once at startup."""
    await asyncio.sleep(3)  # let Flask finish starting up
    data = store.read()
    providers_seen = set()
    for acct in data.get("accounts", []):
        prov = _provider_name(acct)
        if prov in providers_seen:
            continue
        providers_seen.add(prov)
        try:
            if prov == CHATWITHAI_PROVIDER:
                await _chatwithai_fetch_models()
                log.info("Warmed ChatWithAI model cache")
            elif prov == ONEMINAI_PROVIDER:
                await _oneminai_fetch_models()
                log.info("Warmed 1min.AI model cache")
            elif prov == FLOWITH_PROVIDER:
                await _flowith_fetch_models()
                log.info("Warmed Flowith model cache")
        except Exception as e:
            log.warning("Model cache warm-up failed for %s: %s", prov, e)
        await asyncio.sleep(1)


_seed_from_env()


# ═══════════════════════════════════════════════════════════════════════════════
# Quota / usage helpers
# ═══════════════════════════════════════════════════════════════════════════════

_MSG_LOG_LOCK = threading.Lock()

def _mutate_msg_log(fn):
    """Thin wrapper — just delegates to store.mutate() now."""
    store.mutate(fn)


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
# Flowith.io — everything goes through FlowithClient (flowith_webapi module)
# ═══════════════════════════════════════════════════════════════════════════════

_FLOWITH_MODEL_CACHE: dict = {"fetched_at": 0.0, "models": []}


# ── Flowith <think> tag parser (mirrors flowith_webapi) ─────────────────────
_FLOWITH_OPEN_RE  = re.compile(r"<think>",  re.IGNORECASE)
_FLOWITH_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


class _FlowithThinkParser:
    def __init__(self) -> None:
        self._in_think = False

    def feed(self, fragment: str) -> tuple[str, str]:
        visible: list[str] = []
        reasoning: list[str] = []

        while fragment:
            if self._in_think:
                m = _FLOWITH_CLOSE_RE.search(fragment)
                if m:
                    reasoning.append(fragment[: m.start()])
                    fragment = fragment[m.end():]
                    self._in_think = False
                else:
                    reasoning.append(fragment)
                    fragment = ""
            else:
                m = _FLOWITH_OPEN_RE.search(fragment)
                if m:
                    visible.append(fragment[: m.start()])
                    fragment = fragment[m.end():]
                    self._in_think = True
                else:
                    visible.append(fragment)
                    fragment = ""

        return "".join(visible), "".join(reasoning)


def _flowith_split_think(text: str) -> tuple[str, str]:
    parser = _FlowithThinkParser()
    visible, reasoning = parser.feed(text)
    return visible.strip(), reasoning.strip()


async def _flowith_fetch_models() -> list[dict]:
    """Fetch Flowith model catalog with proper category tagging."""
    from datetime import datetime, timezone
    now_ts = datetime.now(timezone.utc).timestamp()
    if _FLOWITH_MODEL_CACHE["models"] and now_ts - _FLOWITH_MODEL_CACHE["fetched_at"] < 900:
        return _FLOWITH_MODEL_CACHE["models"]
    try:
        flowith_acct = next(
            (a for a in store.read().get("accounts", [])
             if _provider_name(a) == FLOWITH_PROVIDER and a.get("api_key")),
            None,
        )
        if not flowith_acct:
            return _FLOWITH_MODEL_CACHE.get("models", [])

        client = await _make_flowith_client(flowith_acct)
        raw    = await client.list_models()
        await client.close()

        models = []
        for m in (raw or []):
            if not m.model_id:
                continue
            media = (m.media or "").lower()
            if any(x in media for x in ("image", "img")):
                category = "image"
            elif any(x in media for x in ("video", "vid")):
                category = "video"
            else:
                category = "text"
            models.append({
                "id":           m.model_id,
                "display_name": m.title or m.model_id,
                "category":     category,
                "tier":         m.tier,
                "media":        m.media or "",
            })

        _FLOWITH_MODEL_CACHE["models"]     = models
        _FLOWITH_MODEL_CACHE["fetched_at"] = now_ts
        return models
    except Exception as exc:
        log.warning("Flowith model fetch failed: %s", exc)
        return _FLOWITH_MODEL_CACHE.get("models", [])


async def _make_flowith_client(acct: dict):
    """Return an authenticated FlowithClient from a stored account dict."""
    token   = acct.get("api_key") or acct.get("session_key", "")
    user_id = acct.get("user_id", "")
    if not token:
        raise ValueError(f"Flowith account '{acct.get('name','?')}' is missing api_key/token")
    client = FlowithClient(token, user_id=user_id or "")
    return client


async def _list_convs_flowith(acct: dict, search: str | None = None, limit: int = 50):
    """List Flowith conversations from the server, merged with local name cache."""
    client = await _make_flowith_client(acct)
    try:
        records = await client.list_conversations(limit=limit)
        await client.close()
    except Exception as exc:
        log.warning("Flowith list_conversations: %s", exc)
        try: await client.close()
        except Exception: pass
        records = []

    # Build local name cache for merge
    local_data = store.read()
    local_names: dict[str, str] = {}
    for a in local_data.get("accounts", []):
        if a["name"] == acct["name"]:
            for c in a.get("pinned_conversations", []):
                cid = c.get("conv_uuid", "")
                dn  = c.get("display_name", "")
                if cid and dn:
                    local_names[cid] = dn
            break

    out = []
    for r in records:
        title = r.title or local_names.get(r.conv_id, "")
        if search and search.lower() not in title.lower():
            continue
        out.append({
            "uuid":       r.conv_id,
            "name":       title,
            "created_at": r.metadata.get("created_at", ""),
            "updated_at": r.metadata.get("updated_at",
                          r.metadata.get("created_at", "")),
        })

    # Also include any locally cached convs not returned by server
    # (e.g. very old ones outside the limit)
    server_ids = {r["uuid"] for r in out}
    for a in local_data.get("accounts", []):
        if a["name"] != acct["name"]:
            continue
        for c in a.get("pinned_conversations", []):
            cid = c.get("conv_uuid", "")
            if cid and cid not in server_ids:
                title = c.get("display_name", "")
                if search and search.lower() not in title.lower():
                    continue
                out.append({
                    "uuid":       cid,
                    "name":       title,
                    "created_at": c.get("created_at", ""),
                    "updated_at": c.get("updated_at", c.get("created_at", "")),
                })
        break

    out.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "",
             reverse=True)
    return out


async def _create_conv_flowith(acct: dict) -> str:
    """Create a real server-side Flowith conversation via Supabase."""
    client = await _make_flowith_client(acct)
    try:
        uid = client._user_id
        if not uid:
            raise ValueError("No user_id in Flowith JWT")
        conv_id = await client._ensure_conversation(None, uid)
        await client.close()
        log.info("Created Flowith server conversation %s", conv_id[:8])
        return conv_id
    except Exception as exc:
        log.warning("Flowith create conversation failed: %s — using local UUID", exc)
        try: await client.close()
        except Exception: pass
        import uuid as _uuid_mod
        return str(_uuid_mod.uuid4())


async def _get_conv_flowith(acct: dict, conv_id: str) -> dict:
    """
    Fetch a Flowith conversation and reconstruct chat_messages from flow nodes.

    Node types: "1" = user, "2" = AI
    Text lives in node.data["value"] (FlowNode.text property).
    Parent chain is reconstructed from node.p_id so branching is preserved.
    """
    root   = "00000000-0000-4000-8000-000000000000"
    client = await _make_flowith_client(acct)
    try:
        nodes = await client.get_flow_nodes(conv_id)
        try:
            conv_record = await client.get_conversation(conv_id)
            conv_title  = conv_record.title or ""
        except Exception:
            conv_title = ""
        await client.close()
    except Exception as exc:
        log.warning("Flowith get_flow_nodes %s: %s", conv_id[:8], exc)
        try: await client.close()
        except Exception: pass
        # Fall back to local cache
        local = _get_local_conv_entry(acct["name"], conv_id)
        if local:
            return {
                "uuid":                      conv_id,
                "name":                      local.get("display_name", ""),
                "created_at":                local.get("created_at", _now()),
                "updated_at":                local.get("updated_at", _now()),
                "chat_messages":             local.get("chat_messages", []),
                "current_leaf_message_uuid": local.get("current_leaf_message_uuid", root),
                "settings":                  {},
            }
        return {
            "uuid": conv_id, "name": "", "created_at": _now(),
            "updated_at": _now(), "chat_messages": [],
            "current_leaf_message_uuid": root, "settings": {},
        }

    # Only user (1) and AI (2) nodes that actually have text content
    message_nodes = [
        n for n in nodes
        if n.node_type in ("1", "2") and (n.text or "").strip()
    ]

    # Build a map of ALL node IDs (including structural) so p_id lookups work
    all_node_ids = {n.node_id for n in nodes}

    messages: list[dict] = []
    # node_id → message uuid mapping (they are the same — flowith node UUIDs)
    node_to_msg_uuid: dict[str, str] = {}

    for i, node in enumerate(message_nodes):
        sender   = "human" if node.node_type == "1" else "assistant"
        text     = node.text  # data["value"]
        msg_uuid = node.node_id  # USE flowith node_id as our message UUID

        # Resolve parent_message_uuid via p_id chain
        p_id = node.p_id or ""
        if not p_id or p_id == conv_id or p_id not in all_node_ids:
            parent_msg_uuid = root
        elif p_id in node_to_msg_uuid:
            parent_msg_uuid = node_to_msg_uuid[p_id]
        else:
            # p_id exists in the graph but wasn't a message node
            # (structural/canvas node) — walk up until we find a message node
            parent_msg_uuid = root
            walked = p_id
            for _ in range(20):  # prevent infinite loop
                parent_node = next((n for n in nodes if n.node_id == walked), None)
                if not parent_node:
                    break
                if parent_node.node_id in node_to_msg_uuid:
                    parent_msg_uuid = node_to_msg_uuid[parent_node.node_id]
                    break
                walked = parent_node.p_id or ""
                if not walked or walked == conv_id:
                    break

        node_to_msg_uuid[node.node_id] = msg_uuid
        messages.append({
            "uuid":                msg_uuid,
            "sender":              sender,
            "text":                text,
            "content":             [{"type": "text", "text": text}],
            "parent_message_uuid": parent_msg_uuid,
            "created_at":          node.metadata.get("created_at", _now()),
            "index":               i,
            "model":               node.model if sender == "assistant" else "",
        })

    # Identify the current leaf: the message node with no children among
    # other message nodes
    msg_uuid_set   = {m["uuid"] for m in messages}
    has_child      = {m["parent_message_uuid"] for m in messages}
    leaf_candidates = [m["uuid"] for m in messages if m["uuid"] not in has_child]
    current_leaf   = leaf_candidates[-1] if leaf_candidates else (
        messages[-1]["uuid"] if messages else root
    )

    # Cache title locally
    if conv_title:
        def fn(data):
            for a in data["accounts"]:
                if a["name"] == acct["name"]:
                    for c in a.get("pinned_conversations", []):
                        if c.get("conv_uuid") == conv_id:
                            if not c.get("display_name"):
                                c["display_name"] = conv_title
                            break
                    break
        store.mutate(fn)

    return {
        "uuid":                      conv_id,
        "name":                      conv_title,
        "created_at":                _now(),
        "updated_at":                _now(),
        "chat_messages":             messages,
        "current_leaf_message_uuid": current_leaf,
        "settings":                  {},
    }


def _sync_stream_flowith(
    acct:            dict,
    conv_id:         str,
    prompt:          str,
    model:           str,
    *,
    asst_uuid:       str,
    parent_node_id:  str | None = None,
    images:          list | None = None,
    timeout:         float = 3600.0,
):
    """
    Stream a Flowith chat turn with branching support.

    parent_node_id — the Flowith node UUID to branch from.
                     Passed as p_id when creating the user node so the
                     conversation tree forks at the correct point.
                     If None / root UUID, starts a new thread from the
                     conversation root.

    Emits Claude-compatible SSE plus an internal flowith_meta event
    carrying the real conv_id and new node UUIDs for local persistence.
    """
    import queue as _queue

    q: "_queue.Queue[bytes | None | Exception]" = _queue.Queue()
    ROOT = "00000000-0000-4000-8000-000000000000"

    def emit(obj: dict) -> bytes:
        return (f"data: {json.dumps(obj, ensure_ascii=False)}\n\n").encode("utf-8")

    async def producer():
        client = await _make_flowith_client(acct)
        try:
            uid = client._user_id
            if not uid:
                raise ValueError("No user_id in Flowith JWT")

            # ── Ensure conversation exists on server ──────────────────────
            real_conv_id = await client._ensure_conversation(conv_id, uid)

            # ── Resolve parent node ID for branching ──────────────────────
            # parent_node_id is a flowith node UUID (same as our message UUID).
            # If it's root/None, pass conv_id as p_id (default behaviour).
            effective_parent = (
                None
                if (not parent_node_id or parent_node_id == ROOT)
                else parent_node_id
            )

            # ── Create user node (with branch p_id if applicable) ─────────
            user_node_id = await client._create_user_node(
                real_conv_id,
                prompt,
                p_id = effective_parent or real_conv_id,
            )

            # ── Create AI node ────────────────────────────────────────────
            ai_node_id = await client._create_ai_node(
                real_conv_id,
                user_node_id,
                model,
            )

            # ── Fire completion request ───────────────────────────────────
            import json as _json
            # Build message content (with image support if applicable)
            if images:
                content_payload = [{"type": "text", "text": prompt}] + [
                    {"type": "image_url", "image_url": {"url": u}}
                    for u in images
                ]
            else:
                content_payload = prompt
            await client._post(
                f"https://edge.flowith.io/completion/async?mode=general",
                {
                    "model":    model,
                    "messages": [{"role": "user", "content": content_payload}],
                    "nodeId":   ai_node_id,
                    "convId":   real_conv_id,
                    "stream":   True,
                },
            )

            q.put(emit({"type": "message_start",
                        "message": {"uuid": asst_uuid, "model": model}}))
            q.put(emit({"type": "content_block_start", "index": 0,
                        "content_block": {"type": "text", "text": ""}}))

            # ── Stream result ─────────────────────────────────────────────
            _result_url   = None
            _result_text  = ""
            _reason_text  = ""
            _think_parser = _FlowithThinkParser()
            _think_started = False
            async for chunk in client._stream_node_events(
                ai_node_id, timeout=timeout
            ):
                evt_type = chunk.get("type", "")
                if evt_type == "chunks":
                    for fragment in chunk.get("chunks", []):
                        if not fragment:
                            continue
                        visible, reasoning = _think_parser.feed(fragment)
                        if reasoning:
                            _reason_text += reasoning
                            if not _think_started:
                                q.put(emit({
                                    "type": "content_block_start",
                                    "index": 1,
                                    "content_block": {"type": "thinking", "thinking": ""},
                                }))
                                _think_started = True
                            q.put(emit({
                                "type":  "content_block_delta",
                                "index": 1,
                                "delta": {"type": "thinking_delta",
                                          "thinking": reasoning},
                            }))
                        if visible:
                            _result_text += visible
                            q.put(emit({
                                "type":  "content_block_delta",
                                "index": 0,
                                "delta": {"type": "text_delta",
                                          "text": visible},
                            }))
                elif evt_type == "complete":
                    raw = chunk.get("result", "")
                    nd  = chunk.get("nodeData") or chunk.get("data") or {}
                    if raw:
                        visible, reasoning = _flowith_split_think(raw)
                        if visible and not _result_text:
                            _result_text = visible
                        if reasoning and not _reason_text:
                            _reason_text = reasoning
                    _result_url = (
                        chunk.get("resultUrl")
                        or chunk.get("imageUrl")
                        or chunk.get("videoUrl")
                        or nd.get("value", "")
                        or raw
                    )
                    if raw and not _result_url:
                        _result_url = raw
                    break
                elif chunk.get("resultUrl") or chunk.get("imageUrl") or chunk.get("videoUrl"):
                    nd = chunk.get("nodeData") or chunk.get("data") or {}
                    _result_url = (
                        chunk.get("resultUrl")
                        or chunk.get("imageUrl")
                        or chunk.get("videoUrl")
                        or nd.get("value", "")
                    )
                    break

            # Detect if result is an image or video URL
            _ru = (_result_url or "").strip()
            _is_img   = bool(_ru) and any(_ru.lower().endswith(x)
                for x in (".png",".jpg",".jpeg",".webp",".gif",".avif"))
            _is_vid   = bool(_ru) and any(_ru.lower().endswith(x)
                for x in (".mp4",".webm",".mov"))
            _is_media = _is_img or _is_vid or (
                bool(_ru) and ("r2-bucket" in _ru or "cdn" in _ru or
                               "blob.core" in _ru or "storage" in _ru or
                               "flowith" in _ru) and
                not _result_text.strip()
            )

            if _is_media and _ru:
                # Replace streaming text blocks with a media block
                # Emit stop for the (possibly empty) text block first
                if _is_img or (not _is_vid and _is_media):
                    q.put(emit({
                        "type":      "flowith_image",
                        "image_url": _ru,
                    }))
                elif _is_vid:
                    q.put(emit({
                        "type":      "flowith_video",
                        "video_url": _ru,
                    }))

            if _think_started:
                q.put(emit({"type": "content_block_stop", "index": 1}))
            q.put(emit({"type": "content_block_stop", "index": 0}))
            q.put(emit({"type": "message_delta",
                        "delta": {"stop_reason": "end_turn"}}))
            q.put(emit({"type": "message_stop"}))

            # ── Internal metadata event (not forwarded to browser) ────────
            q.put(emit({
                "type":         "flowith_meta",
                "real_conv_id": real_conv_id,
                "user_node_id": user_node_id,
                "ai_node_id":   ai_node_id,
            }))

        except Exception as exc:
            log.warning("Flowith stream error: %s", exc)
            q.put(emit({"type": "error",
                        "error": {"type": "api_error", "message": str(exc)}}))
        finally:
            await client.close()
            q.put(None)

    asyncio.run_coroutine_threadsafe(producer(), _loop)
    while True:
        item = q.get()
        if item is None:
            break
        yield item


async def _flowith_get_credits(acct: dict) -> dict | None:
    """Fetch Flowith credit balance."""
    client = await _make_flowith_client(acct)
    try:
        credits_list = await client.get_credits()
        await client.close()
        total = sum(c.remain_quota for c in credits_list)
        result = {
            "total":         total,
            "credits_total": total,
            "entries": [
                {
                    "remain_quota": c.remain_quota,
                    "init_quota":   c.init_quota,
                    "sub_type":     c.sub_type,
                    "from_date":    c.from_date,
                    "to_date":      c.to_date,
                }
                for c in credits_list
            ],
        }
        return result
    except Exception as exc:
        log.warning("Flowith credits for account '%s': %s", acct.get("name","?"), exc)
        try: await client.close()
        except Exception: pass
        return None


async def _flowith_generate_image(
    acct:         dict,
    prompt:       str,
    model:        str  = "gemini-3.1-flash-image",
    aspect_ratio: str  = "1:1",
    conv_id:      str | None = None,
    timeout:      float = 120.0,
) -> dict:
    """Generate an image via Flowith."""
    client = await _make_flowith_client(acct)
    try:
        result = await client.generate_image(
            prompt,
            conv_id      = conv_id,
            model        = model,
            aspect_ratio = aspect_ratio,
            timeout      = timeout,
        )
        await client.close()
        imgs = [{"url": img.url} for img in result.images if img.url]
        return {"images": imgs, "model": result.model, "conv_id": result.conv_id}
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


async def _flowith_generate_video(
    acct:         dict,
    prompt:       str,
    model:        str  = "seedance-2.0-fast",
    aspect_ratio: str  = "16:9",
    conv_id:      str | None = None,
    timeout:      float = 300.0,
) -> dict:
    """Generate a video via Flowith."""
    client = await _make_flowith_client(acct)
    try:
        result = await client.generate_video(
            prompt,
            conv_id      = conv_id,
            model        = model,
            aspect_ratio = aspect_ratio,
            timeout      = timeout,
        )
        await client.close()
        return {"video_url": result.video_url, "model": result.model, "conv_id": result.conv_id}
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


async def _flowith_upsert_online_session(
    acct: dict,
    session_id: str,
    payload: dict,
) -> dict:
    """Upsert an online session in Flowith Supabase."""
    client = await _make_flowith_client(acct)
    # {"p_session_id":"a5c8cfaa-68d0-4542-8d12-3c436322b7e1","p_current_path":"/home","p_device_type":"desktop","p_platform":"linux","p_browser":"firefox","p_locale":"en","p_subscription_tier":"free","p_is_idle":false}
    try:
        result = await client._sb_rpc("upsert_online_session", {
            "p_session_id": session_id,
            "p_current_path": payload.get("current_path", "firefox"),
            "p_device_type": payload.get("device_type", "desktop"),
            "p_platform": payload.get("platform", "linux"),
            "p_browser": payload.get("browser", "firefox"),
            "p_locale": payload.get("locale", "en"),
            "p_subscription_tier": payload.get("subscription_tier", "free"),
            "p_is_idle": payload.get("is_idle", False),
            **payload,
        })
        await client.close()
        return result
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc
    
async def _flowith_remove_online_session(acct: dict, session_id: str) -> dict:
    """Remove an online session in Flowith Supabase."""
    client = await _make_flowith_client(acct)
    try:
        result = await client._sb_rpc("remove_online_session", {
            "p_session_id": session_id,
        })
        await client.close()
        return result
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc

# ── Flowith session cycling (keeps credits refreshed) ────────────────────────

import uuid as _uuid_mod_session

async def _flowith_session_cycle(
    acct: dict,
    *,
    cycles: int = 3,
    delay_sec: float = 1.2,
) -> dict:
    """
    Upsert then remove a throwaway online session N times.
    The server-side RPC refreshes the credit balance on every upsert,
    so cycling ensures the balance is current even if one call fails.
    Returns the last successful upsert payload or {}.
    """
    session_id = str(_uuid_mod_session.uuid4())
    payload = {
        "p_session_id":        session_id,
        "p_current_path":      "/home",
        "p_device_type":       "desktop",
        "p_platform":          "linux",
        "p_browser":           "chrome",
        "p_locale":            "en",
        "p_subscription_tier": "free",
        "p_is_idle":           False,
    }
    last_result: dict = {}
    for i in range(max(1, cycles)):
        # upsert
        try:
            r = await _flowith_upsert_online_session(acct, session_id, payload)
            if isinstance(r, dict):
                last_result = r
            log.debug("Flowith session-cycle upsert %d/%d ok  sid=%s…", i+1, cycles, session_id[:8])
        except Exception as exc:
            log.warning("Flowith session-cycle upsert %d/%d: %s", i+1, cycles, exc)

        await asyncio.sleep(delay_sec)

        # remove
        try:
            await _flowith_remove_online_session(acct, session_id)
            log.debug("Flowith session-cycle remove %d/%d ok", i+1, cycles)
        except Exception as exc:
            log.warning("Flowith session-cycle remove %d/%d: %s", i+1, cycles, exc)

        # rotate session_id so each cycle is a fresh row
        session_id = str(_uuid_mod_session.uuid4())
        payload["p_session_id"] = session_id

        if i < cycles - 1:
            await asyncio.sleep(delay_sec)
            
    # finally, upsert one last time to ensure we end with a fresh session and updated credits
    try:
        r = await _flowith_upsert_online_session(acct, session_id, payload)
        if isinstance(r, dict):
            last_result = r
        log.debug("Flowith session-cycle final upsert ok  sid=%s…", session_id[:8])
    except Exception as exc:
        log.warning("Flowith session-cycle final upsert: %s", exc)

    return last_result


# ═══════════════════════════════════════════════════════════════════════════════
# Flask App
# ═══════════════════════════════════════════════════════════════════════════════

app = Quart(__name__)

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = \
        "Content-Type, X-Account-Name, Cache-Control, Pragma, Expires, X-Frame-Options, X-XSS-Protection, X-Content-Type-Options"
    return response

@app.route("/", methods=["OPTIONS"])
@app.route("/<path:_>", methods=["OPTIONS"])
async def _options_handler(_=None):
    return "", 204

app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
app.config["RESPONSE_TIMEOUT"] = None      # disable response timeout
app.config["BODY_TIMEOUT"] = None          # disable body receive timeout
app.config["KEEP_ALIVE_TIMEOUT"] = 3600   # keep connection alive

# ── Simple API cache (in-memory) ─────────────────────────────────────────────
_API_CACHE = {
    "lock": threading.Lock(),
    "items": {},  # key -> {"expires": ts, "payload": obj}
}


def _cache_key_from_request() -> str:
    qs = request.query_string.decode("utf-8", errors="ignore")
    return f"{request.path}?{qs}" if qs else request.path


def _cache_get(key: str):
    now_ts = datetime.now(timezone.utc).timestamp()
    with _API_CACHE["lock"]:
        item = _API_CACHE["items"].get(key)
        if not item:
            return None
        if item["expires"] < now_ts:
            _API_CACHE["items"].pop(key, None)
            return None
        return item["payload"]


def _cache_set(key: str, payload, ttl_sec: float):
    now_ts = datetime.now(timezone.utc).timestamp()
    with _API_CACHE["lock"]:
        _API_CACHE["items"][key] = {"expires": now_ts + float(ttl_sec), "payload": payload}


def _cache_invalidate(prefix: str):
    with _API_CACHE["lock"]:
        keys = [k for k in _API_CACHE["items"] if k.startswith(prefix)]
        for k in keys:
            _API_CACHE["items"].pop(k, None)


def cache_json(ttl_sec: float = 5.0, key_fn=None):
    def deco(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            if request.method != "GET":
                return await fn(*args, **kwargs)

            key = key_fn() if key_fn else _cache_key_from_request()

            cached = _cache_get(key)
            if cached is not None:
                return jsonify(cached)

            result = await fn(*args, **kwargs)

            try:
                if isinstance(result, tuple):
                    resp, status = result
                    if status == 200 and hasattr(resp, "get_json"):
                        try:
                            data = await resp.get_json()
                            if isinstance(data, dict):
                                _cache_set(key, data, ttl_sec)
                        except Exception:
                            pass
                    elif hasattr(result, "get_json"):
                        try:
                            data = await result.get_json()
                            if isinstance(data, dict):
                                _cache_set(key, data, ttl_sec)
                        except Exception:
                            pass
            except Exception:
                pass

            return result

        return wrapper

    return deco


# ── 1min.AI conversation list ─────────────────────────────────────────────────

async def _list_convs_oneminai(acct: dict, search: str | None = None, limit: int = 50):
    """List 1min.AI conversations via the client library."""
    client = await _make_oneminai_client(acct)
    try:
        records = await client.list_conversations()
        await client.close()
        records = sorted(
            records,
            key=lambda r: r.metadata.get("updatedAt") or r.metadata.get("createdAt") or "",
            reverse=True,
        )
        if search:
            search_lower = search.lower()
            records = [r for r in records if search_lower in (r.title or "").lower()]
        records = records[:limit] if limit else records
        return [
            {
                "uuid":       r.conversation_id,
                "name":       r.title,
                "created_at": r.metadata.get("createdAt", ""),
                "updated_at": r.metadata.get("updatedAt", r.metadata.get("createdAt", "")),
            }
            for r in records
        ]
    except Exception as exc:
        log.warning("1min.AI list_conversations: %s", exc)
        try: await client.close()
        except Exception: pass
        return []


async def _create_conv_oneminai(acct: dict, title: str = "New conversation") -> str:
    """Create a server-side 1min.AI conversation and return its UUID."""
    client = await _make_oneminai_client(acct)
    try:
        rec = await client.create_conversation(title)
        await client.close()
        log.info("1min.AI conversation created: %s", rec.conversation_id[:8])
        return rec.conversation_id
    except Exception as exc:
        log.warning("1min.AI create_conversation: %s", exc)
        try: await client.close()
        except Exception: pass
        return str(uuid_lib.uuid4())   # fallback local UUID


async def _get_conv_oneminai(acct: dict, conv_id: str) -> dict:
    """Fetch a 1min.AI conversation + messages and return Claude-shaped dict."""
    client = await _make_oneminai_client(acct)
    root   = "00000000-0000-4000-8000-000000000000"
    try:
        rec      = await client.get_conversation(conv_id)
        msg_recs = await client.get_conversation_messages(conv_id)
        await client.close()
    except Exception as exc:
        log.warning("1min.AI get_conversation %s: %s", conv_id[:8], exc)
        try: await client.close()
        except Exception: pass
        return {
            "uuid": conv_id, "name": "", "created_at": _now(), "updated_at": _now(),
            "chat_messages": [], "current_leaf_message_uuid": root, "settings": {},
        }

    # Convert MessageRecord list → Claude-shaped chat_messages
    messages: list[dict] = []
    prev_uuid = root
    for i, m in enumerate(msg_recs):
        msg_uuid = (m.record_id or str(uuid_lib.uuid4())) + f"_{i}"
        sender   = "human" if m.role == "USER" else "assistant"
        text     = m.content or ""
        messages.append({
            "uuid":               msg_uuid,
            "sender":             sender,
            "text":               text,
            "content":            [{"type": "text", "text": text}],
            "parent_message_uuid": prev_uuid,
            "created_at":          m.metadata.get("createdAt", _now()),
            "index":               i,
        })
        prev_uuid = msg_uuid

    current_leaf = messages[-1]["uuid"] if messages else root
    return {
        "uuid":                      conv_id,
        "name":                      rec.title,
        "created_at":                rec.metadata.get("createdAt", _now()),
        "updated_at":                rec.metadata.get("updatedAt", _now()),
        "chat_messages":             messages,
        "current_leaf_message_uuid": current_leaf,
        "settings":                  {},
    }


async def _upload_file_oneminai(acct: dict, conv_id: str, f) -> dict:
    """Upload a file to 1min.AI Asset API using the client library."""
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"
    # Determine AssetType from mime
    from oneminai_webapi import AssetType as _AT
    if mime.startswith("image/"):
        atype = _AT.IMAGE
    elif mime.startswith("audio/"):
        atype = _AT.AUDIO
    elif mime.startswith("video/"):
        atype = _AT.VIDEO
    else:
        atype = _AT.DOCUMENT
    client = await _make_oneminai_client(acct)
    try:
        asset = await client.upload_asset(
            data=file_bytes, filename=fname, mime_type=mime, asset_type=atype
        )
        await client.close()
    except Exception as exc:
        log.warning("1min.AI upload_asset: %s", exc)
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc
    _save_upload_meta(acct["name"], conv_id, asset.file_id, fname, len(file_bytes), mime)
    log.info("1min.AI asset: %s → file_id=%s", fname, asset.file_id[:8])
    return {
        "file_uuid":  asset.file_id,
        "asset_key":  asset.asset_key,
        "_upload_ok": True,
        "_filename":  fname,
        "_size":      len(file_bytes),
        "_mime":      mime,
    }

# ── 1min.AI conversation rename ──────────────────────────────────────────────

async def _rename_conv_oneminai(acct: dict, conv_id: str, title: str) -> dict:
    """Rename a 1min.AI conversation via the client library."""
    client = await _make_oneminai_client(acct)
    try:
        rec = await client.rename_conversation(conv_id, title)
        await client.close()
        return {
            "uuid":       rec.conversation_id,
            "name":       rec.title,
            "updated_at": _now(),
        }
    except Exception as exc:
        log.warning("1min.AI rename_conversation %s: %s", conv_id[:8], exc)
        try: await client.close()
        except Exception: pass
        return {"uuid": conv_id, "name": title, "updated_at": _now()}


# ── 1min.AI music generation ──────────────────────────────────────────────────

async def _sync_generate_music_oneminai(
    acct: dict,
    prompt: str,
    model: str,
    instrumental: bool = False,
    duration: float | None = None,
) -> dict:
    """Generate music via 1min.AI using the client library."""
    from oneminai_webapi.constants import MusicModel
    client = await _make_oneminai_client(acct)
    try:
        kwargs: dict = {"instrumental": instrumental}
        if duration is not None:
            kwargs["duration"] = float(duration)
        result = await client.generate_music(prompt, model=model, **kwargs)
        await client.close()
        return {
            "audio_url": result.audio_url,
            "model":     result.model,
            "record_id": result.record_id,
        }
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


# ── 1min.AI image generation ──────────────────────────────────────────────────

async def _sync_generate_image_oneminai(
    acct: dict,
    prompt: str,
    model: str,
    width: int = 1024,
    height: int = 1024,
    num_images: int = 1,
) -> dict:
    """Generate image(s) via 1min.AI using the client library."""
    client = await _make_oneminai_client(acct)
    try:
        result = await client.generate_image(
            prompt,
            model      = model,
            width      = int(width),
            height     = int(height),
            num_images = int(num_images),
        )
        await client.close()
        return {
            "images":    [{"url": img.url} for img in result.images if img.url],
            "model":     result.model,
            "record_id": result.record_id,
        }
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


# ── 1min.AI TTS ───────────────────────────────────────────────────────────────

async def _sync_tts_oneminai(
    acct: dict,
    text: str,
    model: str,
    voice: str,
    speed: float = 1.0,
) -> dict:
    """Text-to-speech via 1min.AI using the client library."""
    client = await _make_oneminai_client(acct)
    try:
        result = await client.text_to_speech(
            text,
            model = model,
            voice = voice,
            speed = float(speed),
        )
        await client.close()
        return {
            "audio_url": result.audio_url,
            "model":     result.model,
            "record_id": result.record_id,
        }
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


# ── 1min.AI content tools ─────────────────────────────────────────────────────

async def _sync_content_tool_oneminai(
    acct: dict,
    tool: str,
    prompt: str,
    **kwargs: str,
) -> str:
    """
    Run a content-tool call via the 1min.AI client library.
    Supported tools: grammar, paraphrase, rewrite, summarize, expand, shorten, translate.
    """
    _TOOL_MAP = {
        "grammar":    "check_grammar",
        "paraphrase": "paraphrase",
        "rewrite":    "rewrite",
        "summarize":  "summarize",
        "expand":     "expand_content",
        "shorten":    "shorten_content",
        "translate":  "translate",
    }
    method_name = _TOOL_MAP.get(tool)
    if not method_name:
        raise ValueError(f"Unknown content tool: {tool!r}")
    client = await _make_oneminai_client(acct)
    try:
        method = getattr(client, method_name)
        language = kwargs.get("language", "English")
        tone     = kwargs.get("tone")
        if tool == "translate":
            result = await method(prompt, language)
        elif tool in ("paraphrase", "rewrite") and tone:
            result = await method(prompt, tone=tone, language=language)
        elif tool in ("summarize", "expand", "shorten"):
            result = await method(prompt, language=language)
        else:
            result = await method(prompt)
        await client.close()
        return result.text
    except Exception as exc:
        try: await client.close()
        except Exception: pass
        raise RuntimeError(str(exc)) from exc


@app.route("/api/ping")
async def ping():
    return jsonify({"ok": True})

# Warm model caches in background after loop is started
def _warm_model_caches_sync():
    asyncio.run_coroutine_threadsafe(_warm_model_caches(), _loop)


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
    async def wrapper(*args, **kwargs):
        acct = _resolve_account(request)

        if not acct:
            name = (
                request.headers.get("X-Account-Name")
                or request.args.get("account_name")
                or ""
            ).strip()

            if name:
                return jsonify({
                    "error": f"Account '{name}' not found"
                }), 404

            return jsonify({
                "error": "No active account configured"
            }), 401

        prov = _provider_name(acct)

        if prov == CLAUDE_PROVIDER and not acct.get("session_key"):
            return jsonify({
                "error": f"Account '{acct['name']}' is missing a session_key"
            }), 401

        if prov == ONEMINAI_PROVIDER and not acct.get("api_key"):
            return jsonify({
                "error": f"Account '{acct['name']}' is missing an api_key"
            }), 401

        if prov == FLOWITH_PROVIDER and not acct.get("api_key"):
            return jsonify({
                "error": f"Account '{acct['name']}' is missing an api_key (Flowith JWT)"
            }), 401

        return await fn(acct, *args, **kwargs)

    return wrapper


def api_error_handler(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)

        except AuthenticationError as exc:
            log.warning("Auth error: %s", exc)

            return jsonify({
                "error": "Authentication failed — check your credentials"
            }), 401

        except APIError as exc:
            log.warning(
                "API error HTTP %s: %s",
                exc.status_code,
                exc,
            )

            return jsonify({
                "error": str(exc),
                "status": exc.status_code
            }), exc.status_code or 500

        except QuotaExceededError as exc:
            return jsonify({
                "error": str(exc)
            }), 429

        except (http_client.TimeoutException, http_client.ReadTimeout):
            return jsonify({
                "error": "Upstream request timed out"
            }), 504

        except http_client.ConnectError:
            return jsonify({
                "error": "Cannot reach upstream API"
            }), 502

        except Exception as exc:
            log.exception("Unhandled error in %s", fn.__name__)

            return jsonify({
                "error": str(exc)
            }), 500

    return wrapper


# ── Health ────────────────────────────────────────────────────────────────────

# ── 1min.AI extra endpoints ───────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
@require_account
@api_error_handler
async def delete_conversation(acct, conv_id):
    """Delete a conversation (all providers)."""
    provider = _provider_name(acct)

    if provider == ONEMINAI_PROVIDER:
        client = await _make_oneminai_client(acct)
        try:
            await client.delete_conversation(conv_id)
            await client.close()
        except Exception as exc:
            log.warning("1min.AI delete_conversation %s: %s", conv_id, exc)
            try: await client.close()
            except Exception: pass

    if provider == FLOWITH_PROVIDER:
        # Flowith doesn't have a delete endpoint in the web API; soft-delete locally
        try:
            client = await _make_flowith_client(acct)
            await client.delete_conversation(conv_id)
            await client.close()
        except Exception as exc:
            log.warning("Flowith delete_conversation %s: %s", conv_id, exc)

    # Remove from local store regardless
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                a["pinned_conversations"] = [
                    c for c in a.get("pinned_conversations", [])
                    if c.get("conv_uuid") != conv_id
                ]
                break
    store.mutate(fn)
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>/rename", methods=["PATCH"])
@require_account
@api_error_handler
async def rename_conversation_route(acct, conv_id):
    """Rename a conversation (all providers)."""
    data  =  await _get_json()
    title = (data.get("title") or data.get("name") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    provider = _provider_name(acct)

    if provider == ONEMINAI_PROVIDER:
        result = await _rename_conv_oneminai(acct, conv_id, title)
        # Also update local metadata
        def fn(store_data):
            for a in store_data["accounts"]:
                if a["name"] == acct["name"]:
                    for c in a.get("pinned_conversations", []):
                        if c.get("conv_uuid") == conv_id:
                            c["display_name"] = title
                            break
                    break
        store.mutate(fn)
        return jsonify({"success": True, "conversation": result})

    if provider == CHATWITHAI_PROVIDER or provider == FLOWITH_PROVIDER:
        def fn(store_data):
            for a in store_data["accounts"]:
                if a["name"] == acct["name"]:
                    for c in a.get("pinned_conversations", []):
                        if c.get("conv_uuid") == conv_id:
                            c["display_name"] = title
                            break
                    break
        store.mutate(fn)
        return jsonify({"success": True, "conversation": {"uuid": conv_id, "name": title}})

    # Claude
    client = await _make_claude_client(acct)
    try:
        await client.update_conversation_settings(conv_id, {"name": title})
    finally:
        await client.close()
    def fn(store_data):
        for a in store_data["accounts"]:
            if a["name"] == acct["name"]:
                for c in a.get("pinned_conversations", []):
                    if c.get("conv_uuid") == conv_id:
                        c["display_name"] = title
                        break
                break
    store.mutate(fn)
    return jsonify({"success": True, "conversation": {"uuid": conv_id, "name": title}})


@app.route("/api/oneminai/music", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_generate_music(acct):
    """Generate music via 1min.AI."""
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    data         = await _get_json()
    prompt       = (data.get("prompt") or "").strip()
    model        = (data.get("model") or "lyria-002").strip()
    instrumental = bool(data.get("instrumental", False))
    duration     = data.get("duration")
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    result = await _sync_generate_music_oneminai(
        acct, prompt, model, instrumental=instrumental,
        duration=float(duration) if duration is not None else None,
    )
    return jsonify(result)


@app.route("/api/oneminai/image", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_generate_image(acct):
    """Generate image(s) via 1min.AI."""
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    data       = await _get_json()
    prompt     = (data.get("prompt") or "").strip()
    model      = (data.get("model") or "black-forest-labs/flux-1.1-pro").strip()
    width      = int(data.get("width", 1024))
    height     = int(data.get("height", 1024))
    num_images = int(data.get("num_images", 1))
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    result = await _sync_generate_image_oneminai(
        acct, prompt, model, width=width, height=height, num_images=num_images
    )
    return jsonify(result)


@app.route("/api/oneminai/tts", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_tts(acct):
    """Text-to-speech via 1min.AI."""
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    data  = await _get_json()
    text  = (data.get("text") or data.get("prompt") or "").strip()
    model = (data.get("model") or "tts-1").strip()
    voice = (data.get("voice") or "alloy").strip()
    speed = float(data.get("speed", 1.0))
    if not text:
        return jsonify({"error": "text is required"}), 400
    result = await _sync_tts_oneminai(acct, text, model, voice, speed)
    return jsonify(result)


@app.route("/api/oneminai/content-tool", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_content_tool(acct):
    """
    Generic content tool endpoint for 1min.AI:
    grammar, paraphrase, rewrite, summarize, expand, shorten, translate.
    """
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    data     = await _get_json()
    tool     = (data.get("tool") or "").strip().lower()
    prompt   = (data.get("prompt") or data.get("text") or "").strip()
    language = (data.get("language") or "English").strip()
    tone     = data.get("tone").strip() if data.get("tone") else None
    kwargs   = {}
    if tone:
        kwargs = {"tone": tone}
    if not tool or not prompt:
        return jsonify({"error": "tool and prompt are required"}), 400
    text = await _sync_content_tool_oneminai(
        acct, tool, prompt, language=language, **kwargs
    )
    return jsonify({"text": text, "tool": tool})


@app.route("/api/health")
async def health():
    acct = _get_active_account()
    provider = _provider_name(acct) if acct else None
    
    result = {
        "status": "ok",
        "store": str(STORE_PATH),
        "account": acct["name"] if acct else None,
        "provider": provider,
    }
    
    if provider:
        models = await _get_models_for_provider(provider)
        result["models_available"] = len(models)
        if provider == CHATWITHAI_PROVIDER:
            result["default_model"] = CHATWITHAI_DEFAULT_MODEL
        elif provider == ONEMINAI_PROVIDER:
            result["default_model"] = ONEMINAI_DEFAULT_MODEL
        elif provider == FLOWITH_PROVIDER:
            result["default_model"] = FLOWITH_DEFAULT_MODEL
        else:
            result["default_model"] = "claude-sonnet-4-6"
    
    return jsonify(result)


_STATE_TTL_SEC = 300  # 5 minutes


def _oauth_gc(data: dict):
    """Remove states older than TTL. Call inside store.mutate()."""
    now = datetime.now(timezone.utc).timestamp()
    states = data.setdefault("_oauth_states", {})
    stale = [
        s for s, e in states.items()
        if e.get("created_at", 0) + _STATE_TTL_SEC < now
    ]
    for s in stale:
        states.pop(s, None)
        log.debug("OAuth GC: dropped stale state %s…", s[:8])


def _oauth_new_state(provider: str) -> str:
    state = secrets.token_hex(16)

    def fn(data):
        _oauth_gc(data)
        data.setdefault("_oauth_states", {})[state] = {
            "provider":    provider,
            "pending_ext": True,
            "done":        False,
            "created_at":  datetime.now(timezone.utc).timestamp(),
        }

    store.mutate(fn)
    log.info("OAuth new state: provider=%s state=%s…", provider, state[:8])
    return state


def _oauth_claim_pending(provider: str) -> str | None:
    # Fast path: check without mutating first
    data = store.read()
    candidate = None
    for state, entry in data.get("_oauth_states", {}).items():
        if (
            entry.get("provider") == provider
            and entry.get("pending_ext")
            and not entry["done"]
        ):
            candidate = state
            break

    if not candidate:
        return None  # nothing waiting — no write needed

    # Slow path: claim it with a mutation
    claimed_state: list[str] = []

    def fn(data):
        states = data.get("_oauth_states", {})
        # Re-check inside the lock in case another worker claimed it first
        entry = states.get(candidate)
        if (
            entry
            and entry.get("pending_ext")
            and not entry["done"]
        ):
            entry["pending_ext"] = False
            claimed_state.append(candidate)
            log.info("OAuth claimed: provider=%s state=%s…", provider, candidate[:8])

    store.mutate(fn)
    return claimed_state[0] if claimed_state else None


def _oauth_complete(state: str, updates: dict) -> bool:
    """Mark state as done. Returns False if already done or not found."""
    completed: list[bool] = [False]

    def fn(data):
        entry = data.get("_oauth_states", {}).get(state)
        if not entry:
            log.warning("OAuth complete: state not found %s…", state[:8])
            return
        if entry.get("done"):
            log.info("OAuth complete: already done %s…", state[:8])
            completed[0] = False
            return
        entry.update(updates)
        entry["done"] = True
        entry["pending_ext"] = False
        completed[0] = True
        log.info("OAuth complete: ok %s…", state[:8])

    store.mutate(fn)
    return completed[0]


def _oauth_read(state: str) -> dict | None:
    """Read a state entry from the shared store. Returns None if not found."""
    data = store.read()
    entry = data.get("_oauth_states", {}).get(state)
    if entry:
        log.info(
            "OAuth read: state=%s… done=%s provider=%s",
            state[:8], entry.get("done"), entry.get("provider")
        )
    else:
        log.warning("OAuth read: state NOT FOUND %s…", state[:8])
    return entry


def _oauth_drop_state(state: str):
    def fn(data):
        data.get("_oauth_states", {}).pop(state, None)
    store.mutate(fn)
    log.info("OAuth drop: state=%s…", state[:8])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/api/oauth/claude/begin")
async def oauth_claude_begin():
    state = _oauth_new_state("claude")
    resp = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/claude/ext-pending")
async def oauth_claude_ext_pending():
    state = _oauth_claim_pending("claude")
    resp  = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/claude/ext-callback", methods=["POST"])
async def oauth_claude_ext_callback():
    data  = await _get_json()
    code  = (data.get("code")  or "").strip()
    state = (data.get("state") or "").strip()
    error = data.get("error")

    if not state:
        return jsonify({"ok": False, "error": "missing_state"}), 400

    entry = _oauth_read(state)
    if not entry or entry.get("provider") != "claude":
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry.get("done"):
        return jsonify({"ok": True})  # idempotent

    if code:
        _oauth_complete(state, {"code": code})
        return jsonify({"ok": True})

    _oauth_complete(state, {"error": error or "no_code"})
    return jsonify({"ok": False, "error": error or "no_code"})


@app.route("/api/oauth/claude/status")
async def oauth_claude_status():
    state = (request.args.get("state") or "").strip()
    if not state:
        return jsonify({"error": "missing_state"}), 400

    entry = _oauth_read(state)
    if entry is None:
        return jsonify({"error": "invalid_state"}), 400
    if not entry.get("done"):
        return jsonify({"done": False})

    resp: dict = {"done": True}
    if "code"  in entry: resp["code"]  = entry["code"]
    if "error" in entry: resp["error"] = entry["error"]

    return jsonify(resp)


@app.route("/api/oauth/claude/owns-state")
async def oauth_claude_owns_state():
    state = request.args.get("state", "")
    entry = _oauth_read(state) if state else None
    return jsonify({"owned": bool(entry and entry.get("provider") == "claude")})


# ── 1min.AI ───────────────────────────────────────────────────────────────────

@app.route("/api/oauth/oneminai/begin")
async def oauth_oneminai_begin():
    state = _oauth_new_state("oneminai")
    resp = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/oneminai/ext-pending")
async def oauth_oneminai_ext_pending():
    state = _oauth_claim_pending("oneminai")
    resp  = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/oneminai/ext-callback", methods=["POST"])
async def oauth_oneminai_ext_callback():
    data        = await _get_json()
    oauth_token = (
        data.get("oauth_token") or data.get("access_token")
        or data.get("token") or ""
    ).strip()
    state = (data.get("state") or "").strip()
    error = data.get("error")

    if not state:
        return jsonify({"ok": False, "error": "missing_state"}), 400

    entry = _oauth_read(state)
    if not entry or entry.get("provider") != "oneminai":
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry.get("done"):
        return jsonify({"ok": True})

    if error:
        _oauth_complete(state, {"error": error})
        return jsonify({"ok": False, "error": error})

    if not oauth_token:
        log.warning("oneminai ext-callback: no token. keys=%s", list(data.keys()))
        _oauth_complete(state, {"error": "no_token"})
        return jsonify({"ok": False, "error": "no_token"}), 400

    # Exchange Google access token → 1min.AI JWT using OneMinAIClient.oauth_login
    try:
        _tmp_client = OneMinAIClient()
        user_rec    = await _tmp_client.oauth_login(oauth_token)
        api_key     = _tmp_client._api_key
        team_id     = user_rec.team_id
        email       = user_rec.email
        await _tmp_client.close()
        _oauth_complete(state, {"api_key": api_key, "team_id": team_id, "email": email})
        log.info("1min.AI OAuth success: %s  team=%s", email, team_id)
        return jsonify({"ok": True, "email": email})
    except Exception as exc:
        log.warning("1min.AI OAuth exchange failed: %s", exc)
        try: await _tmp_client.close()
        except Exception: pass
        _oauth_complete(state, {"error": str(exc)})
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/oauth/oneminai/status")
async def oauth_oneminai_status():
    state = (request.args.get("state") or "").strip()
    if not state:
        return jsonify({"error": "missing_state"}), 400

    entry = _oauth_read(state)
    if entry is None:
        return jsonify({"error": "invalid_state"}), 400
    if not entry.get("done"):
        return jsonify({"done": False})

    resp: dict = {"done": True}
    if "api_key" in entry:
        resp["api_key"] = entry["api_key"]
        resp["team_id"] = entry.get("team_id", "")
        resp["email"]   = entry.get("email", "")
    if "error" in entry:
        resp["error"] = entry["error"]

    return jsonify(resp)


@app.route("/api/oauth/oneminai/owns-state")
async def oauth_oneminai_owns_state():
    state = request.args.get("state", "")
    entry = _oauth_read(state) if state else None
    return jsonify({"owned": bool(entry and entry.get("provider") == "oneminai")})


# ── Flowith ───────────────────────────────────────────────────────────────────

@app.route("/api/oauth/flowith/begin")
async def oauth_flowith_begin():
    state = _oauth_new_state("flowith")
    resp = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/flowith/url")
async def oauth_flowith_url():
    from urllib.parse import urlencode
    state        = request.args.get("state", "")
    SUPABASE_URL = "https://aibdxsebwhalbnugsqel.supabase.co"
    redirect_to  = (
        f"https://flowith.io/#_console_state={state}" if state
        else "https://flowith.io"
    )
    url  = f"{SUPABASE_URL}/auth/v1/authorize?{urlencode({'provider': 'google', 'redirect_to': redirect_to})}"
    resp = jsonify({"url": url, "state": state})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/oauth/flowith/ext-pending")
async def oauth_flowith_ext_pending():
    state = _oauth_claim_pending("flowith")
    resp  = jsonify({"state": state})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"]        = "no-cache"
    return resp


@app.route("/api/oauth/flowith/ext-callback", methods=["POST"])
async def oauth_flowith_ext_callback():
    data          = await _get_json()
    access_token  = (
        data.get("access_token") or data.get("token")
        or data.get("oauth_token") or ""
    ).strip()
    refresh_token = (data.get("refresh_token") or "").strip()
    user_id       = (data.get("user_id")       or "").strip()
    state         = (data.get("state")         or "").strip()
    error         = data.get("error")

    if not state:
        return jsonify({"ok": False, "error": "missing_state"}), 400

    entry = _oauth_read(state)
    if not entry:
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry.get("provider") != "flowith":
        return jsonify({"ok": False, "error": "wrong_provider"}), 400
    if entry.get("done"):
        return jsonify({"ok": True})

    if error:
        _oauth_complete(state, {"error": error})
        return jsonify({"ok": False, "error": error})

    if not access_token:
        log.warning("flowith ext-callback: no token. keys=%s", list(data.keys()))
        _oauth_complete(state, {"error": "no_token"})
        return jsonify({"ok": False, "error": "no_token"}), 400

    if not user_id:
        try:
            import base64 as _b64, json as _json
            parts   = access_token.split(".")
            pad     = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = _json.loads(_b64.urlsafe_b64decode(pad))
            user_id = payload.get("sub", "")
        except Exception:
            pass

    _oauth_complete(state, {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "user_id":       user_id,
    })
    log.info("Flowith OAuth success: user_id=%s", user_id or "(unknown)")
    return jsonify({"ok": True, "user_id": user_id})


@app.route("/api/oauth/flowith/status")
async def oauth_flowith_status():
    state = (request.args.get("state") or "").strip()
    if not state:
        return jsonify({"error": "missing_state"}), 400

    entry = _oauth_read(state)
    if entry is None:
        return jsonify({"error": "invalid_state"}), 400
    if not entry.get("done"):
        return jsonify({"done": False})

    resp: dict = {"done": True}
    if "access_token" in entry:
        resp["access_token"]  = entry["access_token"]
        resp["refresh_token"] = entry.get("refresh_token", "")
        resp["user_id"]       = entry.get("user_id", "")
    if "error" in entry:
        resp["error"] = entry["error"]

    return jsonify(resp)


@app.route("/api/oauth/flowith/owns-state")
async def oauth_flowith_owns_state():
    state = request.args.get("state", "")
    entry = _oauth_read(state) if state else None
    return jsonify({"owned": bool(entry and entry.get("provider") == "flowith")})

# ── 1min.AI Cloudflare clearance — extension-driven cookie relay ──────────────

@app.route("/api/oneminai/cf-begin", methods=["POST"])
async def oneminai_cf_begin():
    """Called by backend when CF clearance is needed. Creates a pending state for the extension to claim."""
    data         = await _get_json()
    account_name = data.get("account_name", "").strip()
    if not account_name:
        return jsonify({"ok": False, "error": "missing_account_name"}), 400

    state = secrets.token_hex(16)

    def fn(store_data):
        pending = store_data.setdefault("_cf_pending", {})
        pending[state] = {
            "account_name": account_name,
            "done": False,
            "cf_clearance": None,
        }

    store.mutate(fn)
    log.info("1min.AI CF clearance requested for account '%s', state=%s…", account_name, state[:8])
    return jsonify({"ok": True, "state": state})

@app.route("/api/oneminai/cf-pending")
async def oneminai_cf_pending():
    """Extension content script polls this; returns the first unsatisfied CF state."""
    for state, entry in store.read().setdefault("_cf_pending", {}).items():
        if not entry["done"]:
            return jsonify({"state": state, "account_name": entry["account_name"]})
    return jsonify({"state": None})


@app.route("/api/oneminai/cf-callback", methods=["POST"])
async def oneminai_cf_callback():
    """Extension POSTs cf_clearance here once it grabs the cookie."""
    data         = await _get_json()
    state        = data.get("state", "")
    cf_clearance = data.get("cf_clearance", "")

    if not state or not cf_clearance:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    store_snapshot = store.read()
    entry = store_snapshot.get("_cf_pending", {}).get(state)
    if not entry:
        return jsonify({"ok": False, "error": "unknown_state"}), 400
    if entry["done"]:
        return jsonify({"ok": True})

    acct_name = entry["account_name"]

    user_agent_hdr = (await _get_json()).get("user_agent", "").strip() if False else ""

    def fn(d):
        pending = d.get("_cf_pending", {})
        if state in pending:
            pending[state]["cf_clearance"] = cf_clearance
            pending[state]["done"] = True
        for a in d["accounts"]:
            if a["name"] == acct_name:
                a["cf_clearance"] = cf_clearance
                break

    store.mutate(fn)
    log.info("1min.AI CF clearance received for account '%s', state=%s…", acct_name, state[:8])
    return jsonify({"ok": True})


@app.route("/api/oneminai/cf-status")
async def oneminai_cf_status():
    """Frontend polls this to know when the CF challenge is resolved."""
    store_snapshot = store.read()
    state = request.args.get("state", "")
    entry = store_snapshot.get("_cf_pending", {}).get(state)
    if not entry:
        return jsonify({"error": "unknown_state"}), 400
    if not entry["done"]:
        return jsonify({"done": False})

    def fn(d):
        d.get("_cf_pending", {}).pop(state, None)

    store.mutate(fn)
    return jsonify({"done": True})
# ── Flowith OAuth (extension-driven flow, similar to OAuth) ───────────────────────────────

@app.route("/api/models", methods=["GET"])
@require_account
async def get_models(acct):
    """Get models for the account resolved from this request's context."""
    provider = _provider_name(acct)
    models   = await _get_models_for_provider(provider)
    default  = (
        CHATWITHAI_DEFAULT_MODEL if provider == CHATWITHAI_PROVIDER else
        ONEMINAI_DEFAULT_MODEL   if provider == ONEMINAI_PROVIDER   else
        FLOWITH_DEFAULT_MODEL    if provider == FLOWITH_PROVIDER     else
        "claude-sonnet-4-6"
    )
    # Group by category for richer UI
    by_cat: dict = {}
    for m in models:
        cat = m.get("category", "text")
        by_cat.setdefault(cat, []).append(m)
    return jsonify({
        "provider":      provider,
        "account":       acct["name"],
        "models":        models,
        "by_category":   by_cat,
        "default_model": default,
        "total":         len(models),
    })


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/a/<path:acct_id>/c/<path:conv_id>")
async def index(acct_id=None, conv_id=None):
    return await render_template("index.html")


# ── Accounts ──────────────────────────────────────────────────────────────────

@app.route("/api/accounts", methods=["GET"])
@cache_json(ttl_sec=30.0)
async def list_accounts():
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

        # Use CACHED models only — never fetch on this endpoint
        if provider == CHATWITHAI_PROVIDER:
            models = _CHATWITHAI_MODEL_CACHE.get("models", [])
        elif provider == ONEMINAI_PROVIDER:
            models = _ONEMINAI_MODEL_CACHE.get("models", [])
        elif provider == FLOWITH_PROVIDER:
            models = _FLOWITH_MODEL_CACHE.get("models", [])
        else:
            models = CLAUDE_MODELS

        if provider == FLOWITH_PROVIDER:
            # Split models by category so the toolbar only sees text/chat models
            text_models  = [m for m in models
                            if m.get("category") in ("text", "chat", None, "")
                            or not m.get("category")]
            pub["models"]        = text_models if text_models else models
            pub["image_models"]  = [m for m in models if m.get("category") == "image"]
            pub["video_models"]  = [m for m in models if m.get("category") == "video"]
        else:
            pub["models"]        = models
        pub["default_model"] = (
            CHATWITHAI_DEFAULT_MODEL if provider == CHATWITHAI_PROVIDER else
            ONEMINAI_DEFAULT_MODEL   if provider == ONEMINAI_PROVIDER   else
            FLOWITH_DEFAULT_MODEL    if provider == FLOWITH_PROVIDER     else
            "claude-sonnet-4-6"
        )
        pub["provider_info"] = {
            "type":                provider,
            "supports_files":      provider in (CLAUDE_PROVIDER, ONEMINAI_PROVIDER),
            "supports_canvas":     provider == CLAUDE_PROVIDER,
            "supports_artifacts":  provider == CLAUDE_PROVIDER,
            "supports_tools":      provider == CLAUDE_PROVIDER,
            "supports_thinking":   provider == CLAUDE_PROVIDER,
            "supports_branching": provider in (CLAUDE_PROVIDER, FLOWITH_PROVIDER, CHATWITHAI_PROVIDER),
            "supports_web_search": provider == ONEMINAI_PROVIDER,
            "supports_image_gen":  provider in (ONEMINAI_PROVIDER, FLOWITH_PROVIDER),
            "supports_video_gen":  provider == FLOWITH_PROVIDER,
            "supports_download":   provider == CLAUDE_PROVIDER,
            "supports_reuse_files": provider in (CLAUDE_PROVIDER, ONEMINAI_PROVIDER),
            "supports_inline_images": provider in (CLAUDE_PROVIDER, FLOWITH_PROVIDER),
            "supports_image_in_chat": provider in (CLAUDE_PROVIDER, FLOWITH_PROVIDER),
        }
        account_list.append(pub)

    return jsonify({"accounts": account_list, "active": active})

@app.route("/api/accounts", methods=["POST"])
async def add_account():
    req  = await _get_json()
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
    oneminai_team_id = (req.get("team_id") or "").strip()
    flowith_api_key      = (req.get("api_key")      or "").strip()
    flowith_user_id      = (req.get("user_id")      or "").strip()
    flowith_refresh_token = (req.get("refresh_token") or "").strip()

    if provider == CLAUDE_PROVIDER and not boot_session_key and not existing_account:
        if claude_code:
            auth_client = await ClaudeClient.from_google_code(
                    claude_code,
                    arkose_session_token=arkose_session_token,
                    organization_id=org or None,
                
            )
            boot_session_key = getattr(auth_client, "_session_key", "")
            boot_org = getattr(auth_client, "_organization_id", None) or org
            await auth_client.close()
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
                if oneminai_team_id:
                    existing["team_id"] = oneminai_team_id
                existing.pop("session_key", None)
                existing.pop("organization_id", None)
            elif provider == FLOWITH_PROVIDER:
                if flowith_api_key:
                    existing["api_key"] = flowith_api_key
                if flowith_user_id:
                    existing["user_id"] = flowith_user_id
                if flowith_refresh_token:
                    existing["refresh_token"] = flowith_refresh_token
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
                if oneminai_team_id:
                    creds["team_id"] = oneminai_team_id
            elif provider == FLOWITH_PROVIDER:
                creds["api_key"] = flowith_api_key
                if flowith_user_id:
                    creds["user_id"] = flowith_user_id
                if flowith_refresh_token:
                    creds["refresh_token"] = flowith_refresh_token
            data["accounts"].append(_new_account(name, provider, **creds))
        if req.get("activate") or len(data["accounts"]) == 1:
            _set_active_in_data(data, name)
        active_name = next(
            (a["name"] for a in data["accounts"] if a.get("is_active")), None)

    store.mutate(fn)
    _cache_invalidate("/api/accounts")
    log.info("Account saved: %s provider=%s active=%s", name, provider, active_name == name)
    return jsonify({"success": True, "name": name,
                    "active": active_name == name}), 201


@app.route("/api/accounts/<n>", methods=["DELETE"])
async def delete_account(n):
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
    _cache_invalidate("/api/accounts")
    return jsonify({"success": True, "active": active_name})


@app.route("/api/accounts/<n>/activate", methods=["POST"])
async def activate_account(n):
    if not _get_account_by_name(n):
        return jsonify({"error": "Account not found"}), 404
    _ensure_single_active(n)
    _cache_invalidate("/api/accounts")
    log.info("Switched active account → %s", n)
    return jsonify({"success": True, "active": n})


# ── Legacy config ─────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
async def get_config():
    acct = _get_active_account()
    provider = _provider_name(acct) if acct else CLAUDE_PROVIDER
    
    # Get available models for the provider
    models = await _get_models_for_provider(provider) if acct else []
    if provider == CHATWITHAI_PROVIDER:
        default_model = CHATWITHAI_DEFAULT_MODEL
    elif provider == ONEMINAI_PROVIDER:
        default_model = ONEMINAI_DEFAULT_MODEL
    elif provider == FLOWITH_PROVIDER:
        default_model = FLOWITH_DEFAULT_MODEL
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
async def set_config():
    data = await _get_json()
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
    _cache_invalidate("/api/accounts")
    return jsonify({"success": True, "active": name})


# ── Preferences ───────────────────────────────────────────────────────────────

@app.route("/api/preferences", methods=["GET"])
@require_account
async def get_preferences(acct):
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            return jsonify(a.setdefault("preferences", {}))
    return jsonify({})


@app.route("/api/preferences", methods=["PATCH"])
@require_account
async def set_preferences(acct):
    prefs = await _get_json()

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
async def list_conversations(acct):
    provider = _provider_name(acct)
    
    metadata_only = request.args.get("metadata_only", "0") == "1"

    if provider == FLOWITH_PROVIDER:
        search = request.args.get("search") or None
        limit  = int(request.args.get("limit", 50))
        convs  = await _list_convs_flowith(acct, search=search, limit=limit)
        if metadata_only:
            convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
        return jsonify(convs), 200

    if provider == ONEMINAI_PROVIDER:
        search = request.args.get("search") or None
        limit  = int(request.args.get("limit", 50))
        convs = await _list_convs_oneminai(acct, search=search, limit=limit)
        if metadata_only:
            convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
        return jsonify(convs), 200

    if provider == CHATWITHAI_PROVIDER:
        data = store.read()
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs = sorted(
                    a.get("pinned_conversations", []),
                    key=lambda c: c.get("updated_at", c.get("created_at", "")),
                    reverse=True,
                )
                if metadata_only:
                    convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
                return jsonify(convs), 200
        return jsonify([]), 200

    # Claude — use local pinned_conversations cache first,
    # only fetch from Claude API if explicitly requested
    force = request.args.get("force", "0") == "1"
    data  = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            cached = a.get("pinned_conversations", [])
            if cached and not force:
                # Return local cache immediately — no Claude API call
                convs = sorted(
                    cached,
                    key=lambda c: c.get("updated_at", c.get("created_at", "")),
                    reverse=True,
                )
                if metadata_only:
                    convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
                return jsonify(convs), 200
            break

    # No local cache — fetch from Claude (slow path, only on first load)
    client = await _make_claude_client(acct)
    try:
        convs = await client.list_conversations()
        # Cache them locally
        def fn(store_data):
            for a in store_data["accounts"]:
                if a["name"] == acct["name"]:
                    existing = {c["conv_uuid"] for c in a.get("pinned_conversations", [])}
                    for c in (convs or []):
                        cid = c.get("uuid") or c.get("id", "")
                        if cid and cid not in existing:
                            a.setdefault("pinned_conversations", []).append({
                                "conv_uuid":    cid,
                                "display_name": c.get("name", ""),
                                "pinned_at":    c.get("updated_at", _now()),
                            })
                    break
        store.mutate(fn)
        if metadata_only:
            convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
        return jsonify(convs), 200
    finally:
        await client.close()


@app.route("/api/conversations", methods=["POST"])
@require_account
@api_error_handler
async def create_conversation(acct):
    provider = _provider_name(acct)

    if provider == FLOWITH_PROVIDER:
        conv_id = await _create_conv_flowith(acct)
        # Cache locally for sidebar speed
        def _cache_flowith_conv(data):
            for a in data["accounts"]:
                if a["name"] == acct["name"]:
                    convs = a.setdefault("pinned_conversations", [])
                    if not any(c["conv_uuid"] == conv_id for c in convs):
                        convs.append({
                            "conv_uuid":    conv_id,
                            "display_name": "",
                            "pinned_at":    _now(),
                            "created_at":   _now(),
                            "updated_at":   _now(),
                            "provider":     FLOWITH_PROVIDER,
                        })
                    break
        store.mutate(_cache_flowith_conv)
        log.info("Created Flowith server conversation %s", conv_id[:8])
        return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201

    if provider == ONEMINAI_PROVIDER:
        conv_id = await _create_conv_oneminai(acct)
        log.info("Created 1min.AI conversation %s", conv_id[:8])
        return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201

    conv_id = str(uuid_lib.uuid4())

    if provider == CHATWITHAI_PROVIDER:
        _upsert_local_conv(acct["name"], conv_id, {
            "display_name": "",
            "created_at": _now(),
            "updated_at": _now(),
            "provider": provider,
        })
        log.info("Created ChatWithAI local conversation %s", conv_id[:8])
        return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201

    client = await _make_claude_client(acct)
    try:
        await client.ensure_conversation(conv_id)
    finally:
        await client.close()

    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct["name"]:
                convs = a.setdefault("pinned_conversations", [])
                if not any(c["conv_uuid"] == conv_id for c in convs):
                    convs.append({"conv_uuid": conv_id, "display_name": "",
                                  "pinned_at": _now()})
                break
    store.mutate(fn)

    log.info("Created Claude conversation %s", conv_id[:8])
    return jsonify({"success": True, "id": conv_id, "uuid": conv_id}), 201


@app.route("/api/conversations/<conv_id>", methods=["GET"])
@require_account
@api_error_handler
async def get_conversation(acct, conv_id):
    provider = _provider_name(acct)

    if provider == FLOWITH_PROVIDER:
        # Always fetch from server for fresh branch/node data
        # Local cache is used as fallback inside _get_conv_flowith
        return jsonify(await _get_conv_flowith(acct, conv_id)), 200

    if provider == ONEMINAI_PROVIDER:
        # Check local store first for speed and offline history
        local = _get_local_conv_entry(acct["name"], conv_id)
        if local and local.get("chat_messages"):
            msgs = local.get("chat_messages", [])
            root_uuid = "00000000-0000-4000-8000-000000000000"
            for i, msg in enumerate(msgs):
                if "uuid" not in msg:
                    msg["uuid"] = str(uuid_lib.uuid4())
                if "parent_message_uuid" not in msg:
                    msg["parent_message_uuid"] = msgs[i-1]["uuid"] if i > 0 else root_uuid
                if "content" not in msg:
                    msg["content"] = [{"type": "text", "text": msg.get("text", "")}]
                if "index" not in msg:
                    msg["index"] = i
                if "sender" not in msg:
                    msg["sender"] = "human" if i % 2 == 0 else "assistant"
                if "created_at" not in msg:
                    msg["created_at"] = local.get("created_at", _now())
            current_leaf = local.get("current_leaf_message_uuid")
            if not current_leaf or current_leaf == root_uuid:
                current_leaf = msgs[-1]["uuid"] if msgs else root_uuid
            return jsonify({
                "uuid": conv_id,
                "name": local.get("display_name", ""),
                "created_at": local.get("created_at", _now()),
                "updated_at": local.get("updated_at", _now()),
                "chat_messages": msgs,
                "current_leaf_message_uuid": current_leaf,
                "settings": local.get("settings", {}),
            }), 200
        # Fall back to 1min.AI API
        return jsonify(await _get_conv_oneminai(acct, conv_id)), 200

    if provider == CHATWITHAI_PROVIDER:
        conv      = _get_local_conv_entry(acct["name"], conv_id)
        root_uuid = "00000000-0000-4000-8000-000000000000"
        if not conv:
            return jsonify({
                "uuid": conv_id, "name": "",
                "created_at": _now(), "updated_at": _now(),
                "chat_messages": [],
                "current_leaf_message_uuid": root_uuid,
                "settings": {}
            }), 200
        messages = conv.get("chat_messages", [])
        for i, msg in enumerate(messages):
            if "uuid"               not in msg: msg["uuid"]               = str(uuid_lib.uuid4())
            if "parent_message_uuid" not in msg:
                msg["parent_message_uuid"] = messages[i-1]["uuid"] if i > 0 else root_uuid
            if "content"            not in msg:
                msg["content"] = [{"type": "text", "text": msg.get("text", "")}]
            if "index"              not in msg: msg["index"]              = i
            if "sender"             not in msg: msg["sender"]             = "human" if i % 2 == 0 else "assistant"
            if "created_at"         not in msg: msg["created_at"]         = conv.get("created_at", _now())
        current_leaf = conv.get("current_leaf_message_uuid")
        if not current_leaf or current_leaf == root_uuid:
            current_leaf = messages[-1]["uuid"] if messages else root_uuid
        return jsonify({
            "uuid": conv_id, "name": conv.get("display_name", ""),
            "created_at": conv.get("created_at", _now()),
            "updated_at": conv.get("updated_at", _now()),
            "chat_messages": messages,
            "current_leaf_message_uuid": current_leaf,
            "settings": conv.get("settings", {})
        }), 200

    # Claude
    client = await _make_claude_client(acct)
    try:
        data = await client.get_conversation(conv_id)
        return jsonify(data), 200
    finally:
        await client.close()


@app.route("/api/conversations/<conv_id>", methods=["PUT"])
@require_account
@api_error_handler
async def update_conversation(acct, conv_id):
    payload  = await _get_json()
    provider = _provider_name(acct)
    new_name = payload.get("name") or payload.get("title") or ""

    if provider == FLOWITH_PROVIDER:
        if new_name:
            _upsert_local_conv(acct["name"], conv_id, {
                "display_name": new_name,
                "updated_at":   _now(),
            })
        return jsonify({"success": True})

    if provider == ONEMINAI_PROVIDER:
        if new_name:
            await _rename_conv_oneminai(acct, conv_id, new_name)
        if new_name:
            def fn(store_data):
                for a in store_data["accounts"]:
                    if a["name"] == acct["name"]:
                        for c in a.get("pinned_conversations", []):
                            if c.get("conv_uuid") == conv_id:
                                c["display_name"] = new_name
                                break
                        break
            store.mutate(fn)
        return jsonify({"success": True})

    if provider == CHATWITHAI_PROVIDER:
        if new_name:
            _upsert_local_conv(acct["name"], conv_id, {
                "display_name": new_name,
                "updated_at":   _now(),
            })
        return jsonify({"success": True})

    # Claude
    client = await _make_claude_client(acct)
    try:
        await client.update_conversation_settings(conv_id, payload)
    finally:
        await client.close()

    if new_name:
        def fn(store_data):
            for a in store_data["accounts"]:
                if a["name"] == acct["name"]:
                    for c in a.get("pinned_conversations", []):
                        if c["conv_uuid"] == conv_id:
                            c["display_name"] = new_name
                            break
                    break
        store.mutate(fn)
    return jsonify({"success": True})


async def _stop_response_flowith(acct, conv_id):
    # Flowith doesn't have a streaming stop endpoint, but we can mark the conversation as stopped locally
    def fn(store_data):
        for a in store_data["accounts"]:
            if a["name"] == acct["name"]:
                for c in a.get("pinned_conversations", []):
                    if c.get("conv_uuid") == conv_id:
                        c["is_streaming"] = False
                        c["updated_at"] = _now()
                        break
                break
    store.mutate(fn)
    
async def _stop_response_oneminai(acct, conv_id):
    # 1min.AI doesn't have a streaming stop endpoint, but we can mark the conversation as stopped locally
    def fn(store_data):
        for a in store_data["accounts"]:
            if a["name"] == acct["name"]:
                for c in a.get("pinned_conversations", []):
                    if c.get("conv_uuid") == conv_id:
                        c["is_streaming"] = False
                        c["updated_at"] = _now()
                        break
                break
    store.mutate(fn)
    
async def _stop_response_claude(acct, conv_id):
    client = await _make_claude_client(acct)
    try:
        await client.stop_response(conv_id)
    except Exception as exc:
        log.warning("Claude stop_response %s: %s", conv_id[:8], exc)
    finally:
        await client.close()
        
async def _stop_response_chatwithai(acct, conv_id):
    # ChatWithAI doesn't have a streaming stop endpoint, but we can mark the conversation as stopped locally
    def fn(store_data):
        for a in store_data["accounts"]:
            if a["name"] == acct["name"]:
                for c in a.get("pinned_conversations", []):
                    if c.get("conv_uuid") == conv_id:
                        c["is_streaming"] = False
                        c["updated_at"] = _now()
                        break
                break
    store.mutate(fn)

@app.route("/api/conversations/<conv_id>/stop", methods=["POST"])
@require_account
@api_error_handler
async def stop_response(acct, conv_id):  
    provider = _provider_name(acct)

    if provider == FLOWITH_PROVIDER:
        await _stop_response_flowith(acct, conv_id)
        return jsonify({"success": True})

    if provider == ONEMINAI_PROVIDER:
        await _stop_response_oneminai(acct, conv_id)
        return jsonify({"success": True})

    if provider == CHATWITHAI_PROVIDER:
        await _stop_response_chatwithai(acct, conv_id)
        return jsonify({"success": True})

    if provider == CLAUDE_PROVIDER:
        await _stop_response_claude(acct, conv_id)
        return jsonify({"success": True})


# ── Messaging ─────────────────────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
@require_account
@api_error_handler
async def send_message(acct, conv_id):
    data = await _get_json()
    provider = _provider_name(acct)

    if provider == FLOWITH_PROVIDER:
        prompt       = (data.get("prompt") or "").strip()
        model        = (data.get("model") or FLOWITH_DEFAULT_MODEL).strip()
        parent_uuid  = data.get("parent_message_uuid",
                                "00000000-0000-4000-8000-000000000000")
        human_uuid   = str(uuid_lib.uuid4())
        asst_uuid    = str(uuid_lib.uuid4())
        ROOT         = "00000000-0000-4000-8000-000000000000"
        _log_message_send(acct["name"], conv_id, model, len(prompt))

        parent_node_id = None if parent_uuid == ROOT else parent_uuid

        # Collect image URLs from attached files (inline image chat)
        raw_files   = data.get("files") or []
        image_urls  = [f["url"] for f in raw_files if isinstance(f, dict) and f.get("url") and
                       (f.get("mime","").startswith("image/") or
                        f.get("_mime","").startswith("image/") or
                        f.get("content_type","").startswith("image/"))]

        text_parts:    list[str] = []
        thinking_parts: list[str] = []
        meta_holder:   list[dict] = []

        media_holder: list[dict] = []  # holds flowith_image / flowith_video

        @stream_with_context
        async def generate_flowith():
            loop = asyncio.get_event_loop()
            q: asyncio.Queue = asyncio.Queue()

            def run_sync():
                try:
                    for chunk in _sync_stream_flowith(
                        acct, conv_id, prompt, model,
                        asst_uuid      = asst_uuid,
                        parent_node_id = parent_node_id,
                        images         = image_urls or None,
                        timeout        = 3600000.0,
                    ):
                        asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                except Exception as exc:
                    err = json.dumps({"type": "error", "error": {"message": str(exc)}})
                    asyncio.run_coroutine_threadsafe(
                        q.put(f"data: {err}\n".encode()), loop
                    )
                finally:
                    asyncio.run_coroutine_threadsafe(q.put(None), loop)

            threading.Thread(target=run_sync, daemon=True).start()

            while True:
                chunk = await q.get()
                if chunk is None:
                    break

                # Parse chunk for side-effects (text accumulation, meta events)
                try:
                    line = chunk.decode("utf-8", errors="replace").strip()
                    skip = False
                    for part in line.splitlines():
                        if not part.startswith("data:"):
                            continue
                        js = part[5:].strip()
                        if not js:
                            continue
                        evt = json.loads(js)
                        etype = evt.get("type", "")
                        if etype == "content_block_delta":
                            delta = evt.get("delta", {})
                            if delta.get("type") == "thinking_delta":
                                thinking_parts.append(delta.get("thinking", ""))
                            else:
                                text_parts.append(delta.get("text", ""))
                        elif etype == "flowith_meta":
                            meta_holder.append(evt)
                            skip = True
                        elif etype in ("flowith_image", "flowith_video"):
                            media_holder.append(evt)
                            skip = True
                    if skip:
                        continue
                except Exception:
                    pass

                yield chunk

            # ── Persist messages locally after stream completes ───────────
            full_response  = "".join(text_parts)
            full_thinking  = "".join(thinking_parts).strip()
            meta           = meta_holder[0] if meta_holder else {}
            real_conv_id   = meta.get("real_conv_id") or conv_id
            user_node_id   = meta.get("user_node_id") or human_uuid
            ai_node_id     = meta.get("ai_node_id")   or asst_uuid

            # Remap conv_id if Flowith created a new one
            if real_conv_id != conv_id:
                def remap(store_data):
                    for a in store_data["accounts"]:
                        if a["name"] != acct["name"]:
                            continue
                        convs = a.setdefault("pinned_conversations", [])
                        convs[:] = [c for c in convs
                                    if c.get("conv_uuid") != conv_id]
                        if not any(c["conv_uuid"] == real_conv_id for c in convs):
                            convs.append({
                                "conv_uuid":    real_conv_id,
                                "display_name": prompt[:40],
                                "pinned_at":    _now(),
                                "created_at":   _now(),
                                "updated_at":   _now(),
                                "provider":     FLOWITH_PROVIDER,
                            })
                        break
                store.mutate(remap)
            else:
                def touch(store_data):
                    for a in store_data["accounts"]:
                        if a["name"] != acct["name"]:
                            continue
                        for c in a.get("pinned_conversations", []):
                            if c.get("conv_uuid") == real_conv_id:
                                c["updated_at"] = _now()
                                if not c.get("display_name"):
                                    c["display_name"] = prompt[:40]
                                break
                        break
                store.mutate(touch)

            actual_parent = parent_uuid
            if parent_uuid == ROOT:
                local_entry = _get_local_conv_entry(acct["name"], real_conv_id)
                local_msgs  = (local_entry or {}).get("chat_messages", [])
                if local_msgs:
                    actual_parent = local_msgs[-1].get("uuid", ROOT)

            human_msg = {
                "uuid":                user_node_id,
                "sender":              "human",
                "text":                prompt,
                "content":             [{"type": "text", "text": prompt}],
                "parent_message_uuid": actual_parent,
                "created_at":          _now(),
            }

            _media_evt  = media_holder[0] if media_holder else None
            _image_url  = _media_evt.get("image_url") if _media_evt and _media_evt.get("type") == "flowith_image" else None
            _video_url  = _media_evt.get("video_url") if _media_evt and _media_evt.get("type") == "flowith_video" else None

            if _image_url:
                asst_content = [{"type": "flowith_image", "url": _image_url}]
                asst_text    = _image_url
            elif _video_url:
                asst_content = [{"type": "flowith_video", "url": _video_url}]
                asst_text    = _video_url
            else:
                asst_content = []
                if full_thinking:
                    asst_content.append({"type": "thinking", "thinking": full_thinking})
                if full_response.strip():
                    asst_content.append({"type": "text", "text": full_response})
                if not asst_content:
                    asst_content = [{"type": "text", "text": full_response}]
                asst_text = full_response

            asst_msg = {
                "uuid":                ai_node_id,
                "sender":              "assistant",
                "text":                asst_text,
                "content":             asst_content,
                "parent_message_uuid": user_node_id,
                "model":               model,
                "created_at":          _now(),
            }
            _append_local_messages(
                acct["name"], real_conv_id, human_msg, asst_msg,
                display_name=prompt[:40] if prompt else "",
            )

        return Response(
            generate_flowith(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"},
        )

    if provider == ONEMINAI_PROVIDER:
        prompt      = (data.get("prompt") or "").strip()
        model       = (data.get("model") or ONEMINAI_DEFAULT_MODEL).strip()
        human_uuid  = str(uuid_lib.uuid4())
        asst_uuid   = str(uuid_lib.uuid4())
        web_search  = bool(data.get("web_search", False))
        _log_message_send(acct["name"], conv_id, model, len(prompt))

        # Collect file UUIDs (oneminai uses fileContent.uuid = file_id)
        raw_files  = data.get("files") or []
        file_uuids = []
        for f in raw_files:
            if isinstance(f, str):
                file_uuids.append(f)
            elif isinstance(f, dict):
                fid = f.get("file_uuid") or f.get("file_id") or f.get("id")
                if fid:
                    file_uuids.append(fid)

        @stream_with_context
        async def generate_oneminai():
            def run_sync():
                try:
                    for chunk in _sync_stream_oneminai(
                        acct, conv_id, prompt, model,
                        human_uuid  = human_uuid,
                        asst_uuid   = asst_uuid,
                        file_uuids  = file_uuids or None,
                        web_search  = web_search,
                    ):
                        asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                finally:
                    asyncio.run_coroutine_threadsafe(q.put(None), loop)

            loop = asyncio.get_event_loop()
            q = asyncio.Queue()
            thread = threading.Thread(target=run_sync, daemon=True)
            thread.start()
            
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk

        return Response(
            generate_oneminai(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if provider == CHATWITHAI_PROVIDER:
        prompt = (data.get("prompt") or "").strip()
        model = (data.get("model") or CHATWITHAI_DEFAULT_MODEL).strip()
        parent_uuid = data.get("parent_message_uuid", "00000000-0000-4000-8000-000000000000")
        human_uuid = str(uuid_lib.uuid4())
        asst_uuid = str(uuid_lib.uuid4())
        ROOT = "00000000-0000-4000-8000-000000000000"

        conv_entry = _get_local_conv_entry(acct["name"], conv_id)

        # Build the branch chain by walking backward from parent_uuid,
        # or use the full stored chain if parent_uuid is ROOT
        history_messages: list[dict] = []
        if conv_entry:
            all_msgs = conv_entry.get("chat_messages", [])
            if all_msgs:
                msg_map = {m["uuid"]: m for m in all_msgs if m.get("uuid")}
                
                if parent_uuid == ROOT:
                    # No branch specified — walk from the active leaf.
                    # 1) Try current_leaf_message_uuid from local entry
                    # 2) Fall back to deepest leaf (longest chain)
                    # 3) Last resort: use all messages in order
                    _active_leaf = (conv_entry or {}).get("current_leaf_message_uuid", "")
                    has_child = {m.get("parent_message_uuid") for m in all_msgs}
                    leaves = [m for m in all_msgs if m.get("uuid") not in has_child]

                    _start_uuid = ""
                    if _active_leaf and _active_leaf != ROOT and _active_leaf in msg_map:
                        _start_uuid = _active_leaf
                    elif leaves:
                        # Pick the leaf with the longest chain back to root
                        _best, _best_len = "", 0
                        for _lf in leaves:
                            _ln = 0
                            _cur = _lf["uuid"]
                            _vis = set()
                            while _cur and _cur != ROOT and _cur in msg_map and _cur not in _vis:
                                _vis.add(_cur)
                                _ln += 1
                                _cur = msg_map[_cur].get("parent_message_uuid", "")
                            if _ln > _best_len:
                                _best_len = _ln
                                _best = _lf["uuid"]
                        _start_uuid = _best

                    if _start_uuid:
                        chain = []
                        visited = set()
                        current = _start_uuid
                        while current and current != ROOT and current not in visited:
                            visited.add(current)
                            node = msg_map.get(current)
                            if not node:
                                break
                            chain.append(node)
                            current = node.get("parent_message_uuid", "")
                        history_messages = list(reversed(chain))
                    else:
                        history_messages = list(all_msgs)
                else:
                    # Branch mode — walk backward from the specified parent
                    chain = []
                    visited = set()
                    current = parent_uuid
                    while current and current != ROOT and current not in visited:
                        visited.add(current)
                        node = msg_map.get(current)
                        if not node:
                            break
                        chain.append(node)
                        current = node.get("parent_message_uuid", "")
                    history_messages = list(reversed(chain))

        # Build ChatWithAI messages array (OpenAI-style roles)
        api_messages = []
        for m in history_messages:
            role = "user" if m.get("sender") == "human" else "assistant"
            text = (m.get("text") or "").strip()
            if text:
                api_messages.append({"role": role, "content": text})
        # Append current user message
        api_messages.append({"role": "user", "content": prompt})

        display_name = data.get("display_name") or (prompt[:30] if prompt else "")
        _log_message_send(acct["name"], conv_id, model, len(prompt))

        text_parts: list[str] = []

        @stream_with_context
        async def generate_chatwithai():
            loop = asyncio.get_event_loop()
            q = asyncio.Queue()

            def run_sync():
                try:
                    for chunk in _sync_stream_chatwithai_messages(
                        api_messages, model, timeout=3600000, assistant_uuid=asst_uuid
                    ):
                        # Parse text parts here too for persistence
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
                                    text_parts.append(
                                        evt.get("delta", {}).get("text", "")
                                    )
                        except Exception:
                            pass
                        asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                finally:
                    asyncio.run_coroutine_threadsafe(q.put(None), loop)

            thread = threading.Thread(target=run_sync, daemon=True)
            thread.start()

            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk

            full_response = "".join(text_parts)

            stored_parent = parent_uuid
            if parent_uuid == ROOT and history_messages:
                stored_parent = history_messages[-1].get("uuid", ROOT)

            human_msg = {
                "uuid": human_uuid,
                "sender": "human",
                "text": prompt,
                "content": [{"type": "text", "text": prompt}],
                "parent_message_uuid": stored_parent,
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
            _append_local_messages(
                acct["name"], conv_id, human_msg, asst_msg,
                display_name=display_name,
            )

        return Response(
            generate_chatwithai(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    payload = build_claude_payload(data)
    _log_message_send(acct["name"], conv_id, payload["model"],
                      len(payload.get("prompt", "")))

    @stream_with_context
    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def run_sync():
            try:
                for chunk in _sync_stream_claude(acct, conv_id, payload):
                    asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
            except Exception as exc:
                err = json.dumps({"type": "error", "error": {"message": str(exc)}})
                asyncio.run_coroutine_threadsafe(
                    q.put(f"data: {err}\n".encode()), loop
                )
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=run_sync, daemon=True).start()

        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk

    return Response(generate(),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── File handling ─────────────────────────────────────────────────────────────

@app.route("/api/conversations/<conv_id>/upload", methods=["POST"])
@require_account
@api_error_handler
async def upload_file(acct, conv_id):
    provider = _provider_name(acct)
    
    if provider == CHATWITHAI_PROVIDER:
        return jsonify({"error": "File uploads not supported for ChatWithAI"}), 400
    if provider == ONEMINAI_PROVIDER:
        if "file" not in await request.files:
            return jsonify({"error": "No file provided"}), 400
        try:
            result = await _upload_file_oneminai(acct, conv_id, (await request.files)["file"])
            logging.info("1min.AI file uploaded to conversation %s", conv_id[:8])
            return jsonify(result), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500
    
    if "file" not in await request.files:
        return jsonify({"error": "No file provided"}), 400
    
    f          = (await request.files)["file"]
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        client = await _make_claude_client(acct)
        try:
            await client.ensure_conversation(conv_id)
            file_uuid = await client.upload_file(conv_id, tmp_path)
        finally:
            await client.close()
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
async def download_file(acct, conv_id):
    file_path = request.args.get("path", "")
    if not file_path:
        return jsonify({"error": "Missing 'path' query parameter"}), 400

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        client = await _make_claude_client(acct)
        try:
            local = await client.download_file(conv_id, file_path, dest=tmpdir)
        finally:
            await client.close()
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

@app.route("/api/oneminai/models", methods=["GET"])
@require_account
@api_error_handler
async def oneminai_list_models(acct):
    """Return 1min.AI model catalog, grouped by category."""
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    try:
        models = await _oneminai_fetch_models()
        # Group by category
        by_cat: dict = {}
        for m in models:
            cat = m.get("category", "text")
            by_cat.setdefault(cat, []).append(m)
        return jsonify({"models": models, "by_category": by_cat, "total": len(models)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/oneminai/upload", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_upload_asset(acct):
    """Upload a file to the 1min.AI Asset API and return asset_key + file_id."""
    provider = _provider_name(acct)
    if provider != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400
    if "file" not in await request.files:
        return jsonify({"error": "No file provided"}), 400

    f          = await request.files["file"]
    file_bytes = f.read()
    mime       = f.content_type or "application/octet-stream"
    fname      = f.filename or "upload"

    from oneminai_webapi import AssetType as _AT2
    _at2 = _AT2.IMAGE if mime.startswith("image/") else            _AT2.AUDIO if mime.startswith("audio/") else            _AT2.VIDEO if mime.startswith("video/") else _AT2.DOCUMENT
    client = await _make_oneminai_client(acct)
    try:
        asset = await client.upload_asset(
            data=file_bytes, filename=fname, mime_type=mime, asset_type=_at2
        )
        await client.close()
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
async def get_usage(acct):
    provider = _provider_name(acct)

    if provider == FLOWITH_PROVIDER:
        credits = await _flowith_get_credits(acct)
        total = (credits.get("total") or credits.get("credits_total")
                 if isinstance(credits, dict) else credits) if credits is not None else None
        return jsonify({"provider": "flowith", "credits": credits, "credits_total": total})

    if provider == ONEMINAI_PROVIDER:
        try:
            client  = await _make_oneminai_client(acct)
            credits = await client.get_team_credits()
            await client.close()
        except Exception as exc:
            log.warning("1min.AI credits fetch: %s", exc)
            try: await client.close()
            except Exception: pass
            credits = None
        return jsonify({"provider": "oneminai", "credits": credits})

    if provider == CHATWITHAI_PROVIDER:
        return jsonify({"provider": "chatwithai"})

    # ── Claude ────────────────────────────────────────────────────────────
    usage = await _fetch_claude_usage(acct)
    if usage:
        _save_quota_snapshot(acct["name"], usage)
        return jsonify({
            "provider": "claude",
            "quota":    usage,
            "windows":  usage.get("windows", {}),
        })

    snap = _get_latest_quota(acct["name"])
    return jsonify({
        "provider": "claude",
        "quota":    snap,
        "windows":  (snap or {}).get("windows", {}),
    })

@app.route("/api/usage/all", methods=["GET"])
async def get_usage_all():
    data    = store.read()
    results = {}
    stagger = float(_POLLING_CFG.get("stagger_delay_sec", 2.5))
    first   = True

    for acct in data["accounts"]:
        name     = acct["name"]
        provider = _provider_name(acct)

        if provider == ONEMINAI_PROVIDER:
            if not acct.get("api_key"):
                results[name] = {"provider": "oneminai", "credits": None}
                continue
            if not first:
                await asyncio.sleep(stagger)
            first = False
            client = None
            try:
                client  = await _make_oneminai_client(acct)
                credits = await client.get_team_credits()
            except Exception as exc:
                log.warning("Credits fetch for %s: %s", name, exc)
                credits = None
            finally:
                if client:
                    try: await client.close()
                    except Exception: pass
            results[name] = {"provider": "oneminai", "credits": credits}

        elif provider == FLOWITH_PROVIDER:
            if not acct.get("api_key"):
                results[name] = {"provider": "flowith", "credits": None}
                continue
            if not first:
                await asyncio.sleep(stagger)
            first = False
            try:
                credits_data = await _flowith_get_credits(acct)
            except Exception as exc:
                log.warning("Flowith credits fetch for %s: %s", name, exc)
                credits_data = None
            _total = None
            if isinstance(credits_data, dict):
                _total = credits_data.get("total") or credits_data.get("credits_total")
            elif credits_data is not None:
                _total = credits_data
            results[name] = {
                "provider":      "flowith",
                "credits":       credits_data,
                "credits_total": _total,
            }

        elif provider == CLAUDE_PROVIDER:
            if not acct.get("session_key"):
                results[name] = {"provider": "claude", "quota": None}
                continue
            if not first:
                await asyncio.sleep(stagger)
            first = False
            usage = await _fetch_claude_usage(acct)
            if usage:
                _save_quota_snapshot(name, usage)
                results[name] = {
                    "provider": "claude",
                    "quota":    usage,
                    "windows":  usage.get("windows", {}),
                }
            else:
                snap = _get_latest_quota(name)
                results[name] = {
                    "provider": "claude",
                    "quota":    snap,
                    "windows":  (snap or {}).get("windows", {}),
                }

        # chatwithai — omit

    return jsonify(results)


@app.route("/api/settings/polling", methods=["GET"])
async def get_polling_config():
    """Return current polling / rate-limit configuration."""
    return jsonify(dict(_POLLING_CFG))


@app.route("/api/settings/polling", methods=["PATCH"])
async def patch_polling_config():
    """Update polling / rate-limit configuration at runtime."""
    data = await _get_json()
    allowed = {"auto_poll_credits", "poll_interval_sec", "stagger_delay_sec", "request_timeout_sec"}
    changed = {}
    for k, v in data.items():
        if k not in allowed:
            continue
        if k == "auto_poll_credits":
            _POLLING_CFG[k] = bool(v)
        else:
            try:
                _POLLING_CFG[k] = float(v)
            except (TypeError, ValueError):
                return jsonify({"error": f"invalid value for {k}"}), 400
        changed[k] = _POLLING_CFG[k]
    log.info("Polling config updated: %s", changed)
    return jsonify({"success": True, "config": dict(_POLLING_CFG)})

@app.route("/api/usage/history", methods=["GET"])
@require_account
async def usage_history(acct):
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
async def usage_messages(acct):
    limit = min(int(request.args.get("limit", 100)), 500)
    data  = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            msgs = a.get("message_log", [])
            return jsonify(list(reversed(msgs[-limit:])))
    return jsonify([])


@app.route("/api/local/conversations", methods=["GET"])
@require_account
async def local_conv_list(acct):
    """Returns pinned/local conversations for the resolved account."""
    
    metadata_only = request.args.get("metadata_only", "0") == "1"
    
    data = store.read()
    for a in data["accounts"]:
        if a["name"] == acct["name"]:
            convs = sorted(
                a.get("pinned_conversations", []),
                key=lambda c: c.get("pinned_at", c.get("updated_at", "")),
                reverse=True,
            )
            if metadata_only:
                convs = [{"conv_uuid": c["conv_uuid"], "display_name": c["display_name"], "provider": c.get("provider", "claude"), "created_at": c.get("created_at"), "updated_at": c.get("updated_at")} for c in convs]
            return jsonify(convs)
    return jsonify([])


@app.route("/api/local/conversations", methods=["POST"])
@require_account
async def local_conv_pin(acct):
    req          = await _get_json()
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
async def local_conv_unpin(acct, conv_uuid):
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
async def local_conv_rename(acct, conv_uuid):
    display_name = (await _get_json()).get("display_name", "")

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
async def list_uploads(acct, conv_uuid):
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
async def update_settings(acct):
    payload = await _get_json()
    client  = await _make_claude_client(acct)
    try:
        await client.patch_settings(payload)
    finally:
        await client.close()
    return jsonify({"success": True})




# ═══════════════════════════════════════════════════════════════════════════════
# Flowith-specific endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/flowith/image", methods=["POST"])
@require_account
@api_error_handler
async def flowith_generate_image(acct):
    """Generate an image via Flowith."""
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400
    data         = await _get_json()
    prompt       = (data.get("prompt") or "").strip()
    model        = (data.get("model") or "gemini-3.1-flash-image").strip()
    aspect_ratio = (data.get("aspect_ratio") or "1:1").strip()
    conv_id      = data.get("conv_id") or None
    timeout      = float(data.get("timeout", 3600.0))
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    result = await _flowith_generate_image(
        acct, prompt, model=model,
        aspect_ratio=aspect_ratio, conv_id=conv_id, timeout=timeout,
    )
    return jsonify(result)


@app.route("/api/flowith/video", methods=["POST"])
@require_account
@api_error_handler
async def flowith_generate_video(acct):
    """Generate a video via Flowith."""
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400
    data         = await _get_json()
    prompt       = (data.get("prompt") or "").strip()
    model        = (data.get("model") or "seedance-2.0-fast").strip()
    aspect_ratio = (data.get("aspect_ratio") or "16:9").strip()
    conv_id      = data.get("conv_id") or None
    timeout      = float(data.get("timeout", 3600))
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    result = await _flowith_generate_video(
        acct, prompt, model=model,
        aspect_ratio=aspect_ratio, conv_id=conv_id, timeout=timeout,
    )
    return jsonify(result)


@app.route("/api/flowith/models", methods=["GET"])
@require_account
@api_error_handler
async def flowith_list_models(acct):
    """Return Flowith model catalog."""
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400
    models = await _flowith_fetch_models()
    by_cat: dict = {}
    for m in models:
        cat = m.get("category", "text")
        by_cat.setdefault(cat, []).append(m)
    return jsonify({"models": models, "by_category": by_cat, "total": len(models)})


@app.route("/api/flowith/credits", methods=["GET"])
@require_account
@api_error_handler
async def flowith_get_credits_route(acct):
    """Return Flowith credit balance."""
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400
    credits = await _flowith_get_credits(acct)  
    return jsonify({"credits": credits})


@app.route("/api/flowith/session-cycle", methods=["POST"])
@require_account
@api_error_handler
async def flowith_session_cycle_route(acct):
    """
    Trigger a Flowith session upsert/remove cycle to refresh credits.
    Body (all optional):
      { "cycles": 3, "delay_sec": 1.0 }
    """
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400
    data     = await _get_json()
    cycles   = int(data.get("cycles",   3))
    delay    = float(data.get("delay_sec", 1.0))
    result   = await _flowith_session_cycle(acct, cycles=cycles, delay_sec=delay)
    # Re-fetch credits after the cycle
    credits  = await _flowith_get_credits(acct)
    return jsonify({"success": True, "session_result": result, "credits": credits})


@app.route("/api/flowith/refresh", methods=["POST"])
@require_account
@api_error_handler
async def flowith_refresh_token_route(acct):
    """
    Exchange a Flowith refresh_token for a new access_token via Supabase.
    Called automatically by the frontend when the JWT nears expiry.
    """
    if _provider_name(acct) != FLOWITH_PROVIDER:
        return jsonify({"error": "Not a Flowith account"}), 400

    refresh_token = acct.get("refresh_token", "").strip()
    if not refresh_token:
        return jsonify({"error": "No refresh_token stored for this account"}), 400

    # Supabase token refresh endpoint
    SUPABASE_URL      = "https://aibdxsebwhalbnugsqel.supabase.co"
    SUPABASE_ANON_KEY = "sb_publishable_qPCinc8LE8ChpdT7Pf79tQ_eryz5udr"

    try:
        async with __import__("aiohttp").ClientSession() as _sess:
            async with _sess.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                json={"refresh_token": refresh_token},
                headers={
                    "apikey":       SUPABASE_ANON_KEY,
                    "Content-Type": "application/json",
                },
                timeout=__import__("aiohttp").ClientTimeout(total=36),
            ) as _resp:
                if not _resp.ok:
                    _err = await _resp.text()
                    raise RuntimeError(f"HTTP {_resp.status}: {_err[:200]}")
                body = await _resp.json(content_type=None)
    except Exception as exc:
        log.warning("Flowith token refresh failed: %s", exc)
        return jsonify({"error": str(exc)}), 502

    new_access  = body.get("access_token",  "")
    new_refresh = body.get("refresh_token", "")

    if not new_access:
        return jsonify({"error": "No access_token in refresh response"}), 502

    # Parse new user_id from JWT sub
    new_user_id = acct.get("user_id", "")
    try:
        import base64 as _b64, json as _json
        parts = new_access.split(".")
        if len(parts) >= 2:
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            new_user_id = _json.loads(_b64.urlsafe_b64decode(pad)).get("sub", new_user_id)
    except Exception:
        pass

    # Persist the new tokens
    acct_name = acct["name"]
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct_name:
                a["api_key"]      = new_access
                a["user_id"]      = new_user_id
                if new_refresh:
                    a["refresh_token"] = new_refresh
                break
    store.mutate(fn)
    _cache_invalidate("/api/accounts")

    log.info("Flowith token refreshed for account %s", acct_name)
    return jsonify({
        "access_token":  new_access,
        "refresh_token": new_refresh,
        "user_id":       new_user_id,
    })
    

@app.route("/api/oneminai/refresh", methods=["POST"])
@require_account
@api_error_handler
async def oneminai_refresh_token_route(acct):
    """
    Refresh a 1min.AI JWT using the client's built-in refresh_token() method.
    Called automatically by the frontend when auth fails.
    """
    if _provider_name(acct) != ONEMINAI_PROVIDER:
        return jsonify({"error": "Not a 1min.AI account"}), 400

    old_key = acct.get("api_key", "").strip()
    if not old_key:
        return jsonify({"error": "No API key stored for this account"}), 400

    client = await _make_oneminai_client(acct)
    try:
        # refresh_token() exchanges the expired token and updates the
        # client's internal _api_key automatically, then returns UserRecord.
        user = await client.refresh_token()
        new_key = client._api_key          # updated by refresh_token()
        team_id = user.team_id or acct.get("team_id", "")
    except Exception as exc:
        log.warning("1min.AI token refresh failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    finally:
        await client.close()

    if not new_key:
        return jsonify({"error": "No new API key returned from refresh"}), 502

    acct_name = acct["name"]
    def fn(data):
        for a in data["accounts"]:
            if a["name"] == acct_name:
                a["api_key"] = new_key
                if team_id:
                    a["team_id"] = team_id
                break
    store.mutate(fn)
    _cache_invalidate("/api/accounts")
    log.info("1min.AI token refreshed for account %s", acct_name)
    return jsonify({"access_token": new_key, "team_id": team_id})
    

async def _main(args):
    config = Config()
    config.bind = [f"{args.host}:{args.port}"]
    config.certfile = "cert.pem"
    config.keyfile  = "key.pem"
    config.alpn_protocols = ["h2", "http/1.1"]
    config.graceful_timeout = 0.1
    config.keep_alive_timeout = 5

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal():
        log.info("Received shutdown signal.")
        shutdown_event.set()
        
        # --- FIX: Force cancel everything hanging in the loop ---
        # This prevents the SSL unhandled exceptions from locking the loop
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task(loop):
                task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    log.info("Starting on https://%s:%d (HTTP/2)", args.host, args.port)
    
    try:
        await serve(app, config, shutdown_trigger=shutdown_event.wait)
    except (asyncio.CancelledError, Exception) as exc:
        # Catch the CancelledError forced by our signal handler
        log.info("Server engine stopped.")
    finally:
        log.info("Saving store...")
        try:
            # Synchronous save safely wrapped in an executor thread
            await loop.run_in_executor(None, store.save)
        except Exception as exc:
            log.warning("Store save error: %s", exc)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    try:
        asyncio.run(_main(args))
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log.info("Bye.")
        os._exit(0)