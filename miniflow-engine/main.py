"""
MiniFlow Engine — FastAPI backend

HTTP:      POST http://localhost:8765/invoke/:command
           GET  http://localhost:8765/health
           GET  http://localhost:8765/callback        ← OAuth token receiver
WebSocket: ws://localhost:8765/ws
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

# ── SSL setup for PyInstaller-frozen builds ──────────────────────────────────
# When frozen, Python can't see the system keychain, so any HTTPS call fails
# with CERTIFICATE_VERIFY_FAILED. Point every SSL-using library at certifi's
# CA bundle BEFORE any of them get imported (requests/httpx/openai/websockets).
if getattr(sys, "frozen", False):
    try:
        import certifi
        _cert = certifi.where()
        os.environ["SSL_CERT_FILE"] = _cert
        os.environ["REQUESTS_CA_BUNDLE"] = _cert
        os.environ["CURL_CA_BUNDLE"] = _cert
    except Exception:
        pass

# tiktoken encodings live in a namespace package; force-import so cl100k_base registers.
try:
    import tiktoken_ext.openai_public  # noqa: F401
except Exception:
    pass

# Tell litellm to use its bundled (offline) cost map instead of fetching
# raw.githubusercontent.com on every request. That GET was adding
# 200–500 ms of latency to each command.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "WARNING")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import config
import agent
import audio
import dictation
import history
import dictionary
import snippets
import styles
import oauth
import llm as llm_module
import hotkey as hotkey_module
from connectors import registry

import pathlib
_log_path = pathlib.Path.home() / "miniflow" / "miniflow.log"
_log_path.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s %(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(_log_path), encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# ── WebSocket connection manager ──

class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)

    async def broadcast(self, event: str, payload: Any):
        msg = json.dumps({"event": event, "payload": payload})
        for ws in list(self.connections):
            try:
                await ws.send_text(msg)
            except Exception:
                self.connections.remove(ws)

manager = ConnectionManager()

# ── App lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("MiniFlow engine starting on http://localhost:8765")
    audio.set_event_broadcaster(manager.broadcast)
    dictation.set_event_broadcaster(manager.broadcast)
    agent.set_event_broadcaster(manager.broadcast)
    # Warm up litellm in the background so the first real LLM call doesn't
    # pay for module init + cost-map load.
    asyncio.create_task(_warm_litellm())
    yield
    log.info("MiniFlow engine shutting down")


async def _warm_litellm():
    try:
        import litellm  # noqa: F401
        from litellm import get_supported_openai_params  # noqa: F401
        import tiktoken
        # Force the cl100k encoding to load so subsequent calls are hot.
        tiktoken.get_encoding("cl100k_base").encode("warmup")
        log.info("litellm + tiktoken warmed up")
    except Exception as e:
        log.warning(f"litellm warmup failed: {e}")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health check ──

@app.get("/health")
async def health():
    return {"status": "ok"}

# ── OAuth callback (receives token from Vercel proxy) ──

_SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head><title>MiniFlow — Connected</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;justify-content:center;align-items:center;
       height:100vh;margin:0;background:#0f1923;color:#fff}
  .box{text-align:center}
  h2{font-size:1.4rem;font-weight:600;margin-bottom:.5rem}
  p{color:#8899aa;font-size:.9rem}
</style></head>
<body><div class="box">
  <h2>✓ Connected successfully</h2>
  <p>You can close this window and return to MiniFlow.</p>
</div></body></html>
"""

_FAIL_HTML = """
<!DOCTYPE html>
<html>
<head><title>MiniFlow — Error</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;justify-content:center;align-items:center;
       height:100vh;margin:0;background:#0f1923;color:#fff}
  .box{text-align:center}
  h2{font-size:1.4rem;font-weight:600;margin-bottom:.5rem;color:#ff6b6b}
  p{color:#8899aa;font-size:.9rem}
</style></head>
<body><div class="box">
  <h2>Connection failed</h2>
  <p>{error}</p>
</div></body></html>
"""

@app.get("/callback")
async def oauth_callback(data: str = "", state: str = ""):
    if not data:
        return HTMLResponse(_FAIL_HTML.format(error="No token data received."), status_code=400)
    try:
        # The Vercel proxy encodes the payload as base64url JSON
        # (or AES-256-GCM if ENCRYPTION_KEY is set on Vercel — we support plain only)
        padding = 4 - len(data) % 4
        padded = data + ("=" * (padding % 4))
        raw = base64.urlsafe_b64decode(padded).decode("utf-8")
        payload = json.loads(raw)
        provider = payload.get("provider")
        if not provider:
            raise ValueError("Missing provider in token payload")
        oauth.save_token(provider, payload)
        log.info(f"OAuth token saved for: {provider}")
        await manager.broadcast("oauth-connected", {"provider": provider})
        return HTMLResponse(_SUCCESS_HTML)
    except Exception as e:
        log.error(f"OAuth callback error: {e}")
        return HTMLResponse(_FAIL_HTML.format(error=str(e)), status_code=400)

# ── WebSocket endpoint ──

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ── Invoke dispatcher ──

async def _start_listening(b: dict):
    bundle_id = b.get("bundleID")
    if bundle_id:
        agent.set_target_app(bundle_id)
    return await audio.start_listening(
        sample_rate=b.get("sampleRate", 16000),
        mode=b.get("mode", "dictation"),
    )


@app.post("/invoke/{command}")
async def invoke(command: str, body: dict = {}):
    handlers = {
        # Audio
        "start_listening":       lambda b: _start_listening(b),
        "stop_listening":        lambda b: audio.stop_listening(),
        "send_audio_chunk":      lambda b: audio.send_audio_chunk(b["chunk"]),
        # Agent
        "execute_command":       lambda b: agent.execute_command(b["command"]),
        # Config
        "save_api_key":          lambda b: config.save_api_key(b["service"], b["key"]),
        "get_api_key":           lambda b: config.get_api_key(b["service"]),
        "has_api_keys":          lambda b: config.has_api_keys(),
        "save_language":         lambda b: config.save_language(b["language"]),
        "get_language":          lambda b: config.get_language(),
        "get_advanced_settings": lambda b: config.get_advanced_settings(),
        "save_advanced_setting": lambda b: config.save_advanced_setting(b["key"], b["value"]),
        "save_user_name":        lambda b: config.save_user_name(b["name"]),
        "get_user_name":         lambda b: config.get_user_name(),
        # Dictation
        "start_dictation":       lambda b: dictation.start_dictation(),
        "stop_dictation":        lambda b: dictation.stop_dictation(),
        "get_dictation_status":  lambda b: dictation.get_dictation_status(),
        "check_accessibility":   lambda b: dictation.check_accessibility(),
        "open_accessibility_settings": lambda b: dictation.open_accessibility_settings(),
        # History
        "get_history":           lambda b: history.get_history(),
        "clear_history":         lambda b: history.clear_history(),
        # OAuth / Connectors
        "start_oauth":           lambda b: oauth.start_oauth(b["provider"]),
        "disconnect_provider":   lambda b: oauth.disconnect_provider(b["provider"]),
        "get_connected_providers": lambda b: oauth.get_connected_providers(),
        "is_provider_connected": lambda b: oauth.is_provider_connected(b["provider"]),
        "list_connectors":       lambda b: registry.list_connectors(),
        # Dictionary
        "add_dictionary_word":   lambda b: dictionary.add_word(b["from"], b["to"]),
        "remove_dictionary_word": lambda b: dictionary.remove_word(b["from"]),
        "get_dictionary":        lambda b: dictionary.get_dictionary(),
        "import_dictionary":     lambda b: dictionary.import_dictionary(b["entries"]),
        # Snippets
        "add_snippet":           lambda b: snippets.add_snippet(b["trigger"], b["expansion"]),
        "remove_snippet":        lambda b: snippets.remove_snippet(b["trigger"]),
        "get_snippets":          lambda b: snippets.get_snippets(),
        # Styles
        "get_style_preferences": lambda b: styles.get_style_preferences(),
        "save_style_preference": lambda b: styles.save_style_preference(b["category"], b["tone"]),
        # LLM providers
        "list_llm_providers":    lambda b: llm_module.list_providers(),
        "get_llm_config":        lambda b: config.get_llm_config(),
        "get_llm_status":        lambda b: config.llm_provider_status(),
        "set_active_llm":        lambda b: config.set_active_llm_provider(b["provider"]),
        "set_llm_model":         lambda b: config.set_llm_provider_model(
                                    b["provider"], b["model"], b.get("base_url")),
        "set_llm_api_key":       lambda b: config.set_llm_api_key(b["provider"], b["api_key"]),
        "clear_llm_api_key":     lambda b: config.clear_llm_api_key(b["provider"]),
        "get_llm_keys_file":     lambda b: {"path": config.llm_keys_file_path()},
        # Hotkey
        "get_hotkey":            lambda b: hotkey_module.get_hotkey(),
        "set_hotkey":            lambda b: hotkey_module.set_hotkey(b),
        "reset_hotkey":          lambda b: hotkey_module.reset_hotkey(),
        # App
        "open_settings":         lambda b: None,
    }

    handler = handlers.get(command)
    if not handler:
        return {"error": f"Unknown command: {command}"}

    try:
        result = handler(body)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    except Exception as e:
        log.error(f"[{command}] {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    import uvicorn

    # When frozen (PyInstaller bundle), GUI apps don't inherit shell env vars —
    # SSL_CERT_FILE / REQUESTS_CA_BUNDLE are unset and all HTTPS calls fail.
    # Auto-configure from the certifi bundle that PyInstaller packages.
    if getattr(sys, "frozen", False):
        try:
            import certifi
            cert = certifi.where()
            os.environ.setdefault("SSL_CERT_FILE", cert)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", cert)
        except Exception:
            pass

    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)
