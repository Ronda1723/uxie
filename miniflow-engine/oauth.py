"""OAuth — delegates to Railway (uxie-backend) so the desktop app never
ships provider client_secrets.

Flow:
    1. Mac calls start_oauth("google") → returns a Railway URL
       (https://uxie-production.up.railway.app/oauth/google/start?
            token=<our-jwt>&redirect=http://localhost:8765/oauth/google/done)
    2. Electron opens that URL in the user's browser.
    3. Railway validates our JWT, redirects to Google, handles the
       callback, stores the OAuth token in Railway's DB.
    4. Railway 302s back to http://localhost:8765/oauth/google/done.
    5. Our local FastAPI server (in main.py) returns the success page and
       broadcasts `oauth-connected` over WS so the renderer refreshes.

For tool execution, get_token("google") hits Railway's
`/user/connector_token/google` to grab a short-lived access_token
(refreshed server-side via the stored refresh_token). The local
~/miniflow/connectors.json file is no longer used as a source of
truth — only as a process-local cache to avoid hitting Railway on
every Gmail API call.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

import config

log = logging.getLogger("oauth")

CONNECTORS_FILE = Path.home() / "miniflow" / "connectors.json"

# Local connector redirect — Railway redirects the browser here after a
# successful OAuth handshake. Our FastAPI server (main.py) serves
# /oauth/{provider}/done and shows the "you can close this tab" page.
LOCAL_REDIRECT_BASE = "http://localhost:8765/oauth"

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

# Process-local cache so we don't hit Railway every time the agent loop
# wants the Gmail access_token. Keyed by provider → (access_token,
# expires_at_epoch). Refilled from Railway when the cached entry is
# within 60 s of expiry.
_token_cache: dict[str, dict[str, Any]] = {}
_TOKEN_CACHE_GRACE_SECONDS = 60


def _railway_url(path: str) -> str:
    return f"{config.get_uxie_backend_url()}{path}"


def _auth_headers() -> dict[str, str]:
    jwt = config.get_jwt()
    if not jwt:
        raise RuntimeError("Not signed in — call /auth flow first")
    return {"Authorization": f"Bearer {jwt}", "Accept": "application/json"}


def get_connected_providers() -> list:
    """Ask Railway which connectors this user has. Returns [] if offline."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(_railway_url("/user/connections"), headers=_auth_headers())
            r.raise_for_status()
            return list(r.json().get("connected", []))
    except Exception as e:
        log.warning(f"get_connected_providers failed: {e}")
        return []


def is_provider_connected(provider: str) -> bool:
    return provider in get_connected_providers()


def disconnect_provider(provider: str):
    """Remove the user's stored OAuth token on Railway."""
    _token_cache.pop(provider, None)
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.delete(_railway_url(f"/user/connections/{provider}"), headers=_auth_headers())
            r.raise_for_status()
        log.info(f"Disconnected: {provider}")
    except Exception as e:
        log.warning(f"disconnect_provider({provider}) failed: {e}")


def get_token(provider: str) -> dict | None:
    """Return a fresh access_token dict for `provider` (refreshed by
    Railway if needed). Shape: {"access_token": "...", "provider": "..."}.
    Returns None if not connected or the user is offline."""
    cached = _token_cache.get(provider)
    if cached and cached.get("expires_at_epoch", 0) - time.time() > _TOKEN_CACHE_GRACE_SECONDS:
        return cached
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(_railway_url(f"/user/connector_token/{provider}"), headers=_auth_headers())
            if r.status_code == 404:
                return None  # not connected
            r.raise_for_status()
            body = r.json()
    except Exception as e:
        log.warning(f"get_token({provider}) failed: {e}")
        return None

    # Compute an epoch expiry from the ISO timestamp Railway returns.
    expires_at = body.get("expires_at")
    expires_epoch = 0
    if expires_at:
        try:
            from datetime import datetime
            # Python ISO parser accepts the Z suffix in 3.11+; older
            # versions need it replaced with +00:00.
            iso = expires_at.replace("Z", "+00:00")
            expires_epoch = datetime.fromisoformat(iso).timestamp()
        except Exception:
            expires_epoch = time.time() + 3000  # conservative fallback

    out = {
        "access_token": body.get("access_token"),
        "provider": provider,
        "scope": body.get("scope"),
        "expires_at_epoch": expires_epoch,
    }
    _token_cache[provider] = out
    return out


def save_token(provider: str, token_data: dict):
    """No-op stub. Token storage now lives on Railway; we keep this for
    callers that haven't been migrated, but it's effectively a write to
    /dev/null. Use Railway's /oauth/{provider}/start flow to set tokens."""
    log.debug(f"save_token({provider}) ignored — tokens are stored on Railway")


# ── OAuth flow ────────────────────────────────────────────────────────────────


def start_oauth(provider: str) -> str:
    """Return the Railway URL that begins the OAuth handshake. The Mac
    UI opens this in the system browser. After Google accepts, Railway
    redirects back to http://localhost:8765/oauth/{provider}/done, which
    our local FastAPI server serves (and broadcasts oauth-connected on)."""
    if provider not in {"google"}:
        raise ValueError(
            f"OAuth for '{provider}' isn't routed through Railway yet — only Google is supported"
        )
    jwt = config.get_jwt()
    if not jwt:
        raise RuntimeError("Sign in to Uxie first (no JWT in keychain)")
    redirect = f"{LOCAL_REDIRECT_BASE}/{provider}/done"
    qs = f"token={jwt}&redirect={redirect}"
    return f"{config.get_uxie_backend_url()}/oauth/{provider}/start?{qs}"


async def handle_callback(code: str, state: str) -> str:
    """Legacy local-loopback callback handler. Retained so the old
    /callback route in main.py still compiles, but the new Railway-
    routed flow doesn't call it. Returns the provider name on best-effort."""
    log.warning("handle_callback called — this path is deprecated; OAuth goes through Railway now")
    return "unknown"


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
