"""OAuth — local loopback (RFC 8252). Zero external dependencies."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("oauth")

REDIRECT_URI = "http://localhost:8765/callback"
CONNECTORS_FILE = Path.home() / "miniflow" / "connectors.json"

# ── Provider registry ─────────────────────────────────────────────────────────
# Fill in client_id / client_secret for each provider you've registered.
# For development, env vars override the hardcoded values.

PROVIDERS: dict[str, dict] = {
    "google": {
        "auth_url":      "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":     "https://oauth2.googleapis.com/token",
        "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "use_pkce": True,
    },
    "slack": {
        "auth_url":      "https://slack.com/oauth/v2/authorize",
        "token_url":     "https://slack.com/api/oauth.v2.access",
        "client_id":     os.getenv("SLACK_CLIENT_ID", "SLACK_CLIENT_ID_HERE"),
        "client_secret": os.getenv("SLACK_CLIENT_SECRET", "SLACK_CLIENT_SECRET_HERE"),
        "scopes": [],
        "extra_params": {
            "user_scope": (
                "channels:read,channels:history,groups:read,groups:history,"
                "chat:write,users:read,search:read,im:read,im:history,"
                "mpim:read,mpim:history"
            ),
        },
        "use_pkce": False,
    },
}

# ── PKCE ──────────────────────────────────────────────────────────────────────

def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge

# in-flight state: state_token → {provider, verifier}
_pending: dict[str, dict[str, Any]] = {}

# ── Token storage ─────────────────────────────────────────────────────────────

def _read() -> dict:
    try:
        if CONNECTORS_FILE.exists():
            return json.loads(CONNECTORS_FILE.read_text())
    except Exception:
        pass
    return {}

def _write(data: dict):
    CONNECTORS_FILE.parent.mkdir(exist_ok=True)
    CONNECTORS_FILE.write_text(json.dumps(data, indent=2))

def get_connected_providers() -> list:
    return list(_read().keys())

def is_provider_connected(provider: str) -> bool:
    return provider in _read()

def disconnect_provider(provider: str):
    data = _read()
    data.pop(provider, None)
    _write(data)
    log.info(f"Disconnected: {provider}")

def get_token(provider: str) -> dict | None:
    return _read().get(provider)

def save_token(provider: str, token_data: dict):
    data = _read()
    data[provider] = token_data
    _write(data)

# ── OAuth flow ────────────────────────────────────────────────────────────────

async def start_oauth(provider: str) -> str:
    """Build and return the provider's OAuth authorize URL."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Unknown provider: {provider}")

    state = secrets.token_urlsafe(16)
    pending: dict[str, Any] = {"provider": provider, "verifier": ""}

    params: dict[str, str] = {
        "client_id":     cfg["client_id"],
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "state":         state,
    }

    if cfg["scopes"]:
        params["scope"] = " ".join(cfg["scopes"])

    if cfg["use_pkce"]:
        verifier, challenge = _pkce_pair()
        pending["verifier"] = verifier
        params["code_challenge"]        = challenge
        params["code_challenge_method"] = "S256"

    params.update(cfg.get("extra_params", {}))
    _pending[state] = pending

    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{cfg['auth_url']}?{qs}"


async def handle_callback(code: str, state: str) -> str:
    """Exchange auth code for tokens. Returns provider name."""
    pending = _pending.pop(state, None)
    if pending is None:
        raise ValueError("Unknown or expired OAuth state — try connecting again.")

    provider = pending["provider"]
    cfg = PROVIDERS[provider]

    post_data: dict[str, str] = {
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }
    if pending["verifier"]:
        post_data["code_verifier"] = pending["verifier"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=post_data)
        resp.raise_for_status()
        token_data = resp.json()

    if token_data.get("error"):
        raise ValueError(f"Token exchange failed: {token_data.get('error_description', token_data['error'])}")

    token_data["provider"] = provider
    save_token(provider, token_data)
    log.info(f"OAuth complete: {provider}")
    return provider


async def refresh_token(provider: str) -> dict | None:
    """Refresh an expired access token. Returns updated token dict or None."""
    token = get_token(provider)
    if not token or not token.get("refresh_token"):
        return None

    cfg = PROVIDERS.get(provider)
    if not cfg:
        return None

    post_data = {
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type":    "refresh_token",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=post_data)
        resp.raise_for_status()
        new_token = resp.json()

    if new_token.get("error"):
        log.warning(f"Token refresh failed for {provider}: {new_token.get('error')}")
        return None

    # Google doesn't re-issue refresh_token on refresh — preserve the old one
    if not new_token.get("refresh_token"):
        new_token["refresh_token"] = token["refresh_token"]
    new_token["provider"] = provider
    save_token(provider, new_token)
    log.info(f"Token refreshed: {provider}")
    return new_token
