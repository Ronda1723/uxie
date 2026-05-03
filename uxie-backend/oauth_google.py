"""
OAuth flow for Google Gmail / Calendar / Drive on iOS + macOS clients.

Flow:
    1. Client opens   /oauth/google/start?token=<JWT>&redirect=<custom_scheme>
    2. We validate the JWT, generate a random `state`, stash
       { state → (user_id, redirect_target) } in memory (TTL 10 min),
       then 302 to Google's consent page.
    3. User accepts at accounts.google.com.
    4. Google redirects back to /oauth/google/callback?code=<>&state=<>
    5. We swap `code` for tokens at oauth2.googleapis.com/token, upsert
       the OAuthToken row for this user, and 302 to the original
       `redirect_target` (typically a custom URL scheme like
       uxie://oauth/google/done) so ASWebAuthenticationSession on iOS
       closes itself.

Env vars required on Railway:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET

The OAuth client in Google Cloud Console must have
    https://uxie-production.up.railway.app/oauth/google/callback
in its authorized redirect URIs list.
"""

from __future__ import annotations

import os
import secrets
import time
from urllib.parse import urlencode

import fastapi
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user_from_token  # JWT verifier
from db import get_db
from db_ios import OAuthToken
from proxy import get_http
from settings import get_settings

# ── Provider config ───────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

CALLBACK_PATH = "/oauth/google/callback"


def _public_callback_url(request: Request) -> str:
    """Build the public-facing callback URL.

    Behind Railway's reverse proxy, `request.url_for(...)` returns http://
    because the internal connection from the proxy to our process is HTTP,
    even though the client hit Railway over HTTPS. Trust the standard
    X-Forwarded-Proto / X-Forwarded-Host headers so the URL we hand to
    Google matches the one in the OAuth client's authorized redirect list.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    proto = proto.split(",")[0].strip().lower() or "https"
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    host = host.split(",")[0].strip()
    return f"{proto}://{host}{CALLBACK_PATH}"

# ── In-flight state ──────────────────────────────────────────────────────────
# Map random state token → { user_id, client_redirect, expires_at }.
# Single-process / memory-only is fine for Phase 0.7 since OAuth is rare; we
# can move to Redis if we ever shard the backend.

_PENDING: dict[str, dict] = {}
_PENDING_TTL_SECONDS = 600  # 10 min — Google's consent flow is leisurely


def _gc() -> None:
    """Drop expired pending states. Called at the top of every request."""
    now = time.time()
    expired = [s for s, v in _PENDING.items() if v["expires_at"] < now]
    for s in expired:
        _PENDING.pop(s, None)


# ── /oauth/google/start ──────────────────────────────────────────────────────


async def start(
    request: Request,
    token: str,
    redirect: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Kick off the OAuth flow. Validates the JWT we baked into the URL,
    stashes user_id under a random state token, then redirects the browser
    to Google's consent screen."""
    _gc()

    settings = get_settings()
    client_id = (settings.google_client_id or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    if not client_id:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID missing).")

    # Validate JWT — we accept the bearer token via query param because
    # ASWebAuthenticationSession can't easily inject Authorization headers.
    user = await current_user_from_token(token, db)
    if user is None:
        raise HTTPException(401, "Invalid or expired token.")

    state = secrets.token_urlsafe(24)
    _PENDING[state] = {
        "user_id": user.id,
        "client_redirect": redirect or "uxie://oauth/google/done",
        "expires_at": time.time() + _PENDING_TTL_SECONDS,
    }

    callback_url = _public_callback_url(request)
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": " ".join(GOOGLE_SCOPES),
        "response_type": "code",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)


# ── /oauth/google/callback ───────────────────────────────────────────────────


async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Google redirects here with `code` after the user accepts. Swap for
    tokens and 302 the user back to the originating client redirect."""
    _gc()

    if error:
        return _client_redirect_error(state, f"Google returned: {error}")
    if not code or not state:
        return _client_redirect_error(state, "Missing code or state.")

    pending = _PENDING.pop(state, None)
    if pending is None:
        return _client_redirect_error(state, "Session expired or invalid state.")

    settings = get_settings()
    client_id = (settings.google_client_id or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    client_secret = (settings.google_client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        return _client_redirect_error(state, "Google OAuth not configured on server.")

    callback_url = _public_callback_url(request)

    http = get_http()
    resp = await http.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": callback_url,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        return _client_redirect_error(
            state, f"Token exchange failed ({resp.status_code}): {resp.text[:200]}"
        )
    tok = resp.json()

    # Upsert into OAuthToken for this user.
    user_id = pending["user_id"]
    existing = (await db.execute(
        select(OAuthToken).where(
            OAuthToken.user_id == user_id, OAuthToken.provider == "google"
        )
    )).scalar_one_or_none()

    if existing:
        existing.access_token = tok["access_token"]
        if tok.get("refresh_token"):
            existing.refresh_token = tok["refresh_token"]
        existing.token_type = tok.get("token_type", "Bearer")
        existing.scope = tok.get("scope")
        existing.extra_json = {"id_token": tok.get("id_token")}
    else:
        db.add(OAuthToken(
            user_id=user_id,
            provider="google",
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            token_type=tok.get("token_type", "Bearer"),
            scope=tok.get("scope"),
            extra_json={"id_token": tok.get("id_token")},
        ))
    await db.commit()

    return RedirectResponse(url=pending["client_redirect"], status_code=302)


# ── Error redirect helper ────────────────────────────────────────────────────


def _client_redirect_error(state: str | None, message: str) -> RedirectResponse:
    """Land back on the iOS client's custom scheme even on failure, so the
    in-app browser dismisses cleanly. iOS-side handler can show the message."""
    target = "uxie://oauth/google/error"
    pending = _PENDING.pop(state, None) if state else None
    if pending and pending.get("client_redirect"):
        target = pending["client_redirect"].rstrip("/").replace("/done", "/error")
    return RedirectResponse(
        url=f"{target}?{urlencode({'message': message})}", status_code=302
    )
