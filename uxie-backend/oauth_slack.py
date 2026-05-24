"""OAuth v2 flow for Slack — parallels oauth_google.py.

Required env vars on Railway:
    SLACK_CLIENT_ID
    SLACK_CLIENT_SECRET

Required Slack app config (api.slack.com → Your App → OAuth & Permissions):
    Redirect URLs:
        https://uxie-production.up.railway.app/oauth/slack/callback
    User Token Scopes (we ask for these so search.messages /
    conversations.history actually return data for the user, not just
    public-bot-accessible channels):
        channels:read
        channels:history
        groups:read
        groups:history
        im:read
        im:history
        mpim:read
        mpim:history
        chat:write
        users:read
        search:read

Bot Token Scopes (minimum, kept narrow):
    channels:read     — so chat.postMessage can resolve #channel names

Without these env vars the start endpoint 500s with a clear error and the
client UI hides the Connect Slack button.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user_from_token
from db import get_db
from db_ios import OAuthToken
from proxy import get_http

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"

SLACK_USER_SCOPES = ",".join([
    "channels:read", "channels:history",
    "groups:read",   "groups:history",
    "im:read",       "im:history",
    "mpim:read",     "mpim:history",
    "chat:write",    "users:read",     "search:read",
])
SLACK_BOT_SCOPES = "channels:read"

CALLBACK_PATH = "/oauth/slack/callback"


def _public_callback_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    proto = proto.split(",")[0].strip().lower() or "https"
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    host = host.split(",")[0].strip()
    return f"{proto}://{host}{CALLBACK_PATH}"


# Same in-memory pending-state model as oauth_google.py.
_PENDING: dict[str, dict] = {}
_PENDING_TTL_SECONDS = 600


def _gc() -> None:
    now = time.time()
    for s in [k for k, v in _PENDING.items() if v["expires_at"] < now]:
        _PENDING.pop(s, None)


async def start(
    request: Request,
    token: str,
    redirect: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    _gc()
    client_id = (os.getenv("SLACK_CLIENT_ID") or "").strip()
    if not client_id:
        raise HTTPException(500, "Slack OAuth not configured (SLACK_CLIENT_ID missing).")

    user = await current_user_from_token(token, db)
    if user is None:
        raise HTTPException(401, "Invalid or expired token.")

    state = secrets.token_urlsafe(24)
    _PENDING[state] = {
        "user_id": user.id,
        "client_redirect": redirect or "uxie://oauth/slack/done",
        "expires_at": time.time() + _PENDING_TTL_SECONDS,
    }

    params = {
        "client_id": client_id,
        "scope": SLACK_BOT_SCOPES,
        "user_scope": SLACK_USER_SCOPES,
        "redirect_uri": _public_callback_url(request),
        "state": state,
    }
    return RedirectResponse(url=f"{SLACK_AUTHORIZE_URL}?{urlencode(params)}", status_code=302)


async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    _gc()
    if error:
        return _redirect_err(state, f"Slack returned: {error}")
    if not code or not state:
        return _redirect_err(state, "Missing code or state.")
    pending = _PENDING.pop(state, None)
    if pending is None:
        return _redirect_err(state, "Session expired or invalid state.")

    client_id = (os.getenv("SLACK_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SLACK_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return _redirect_err(state, "Slack OAuth not configured on server.")

    http = get_http()
    resp = await http.post(
        SLACK_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _public_callback_url(request),
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        return _redirect_err(state, f"Token exchange failed ({resp.status_code}): {resp.text[:200]}")
    tok = resp.json()
    if not tok.get("ok"):
        return _redirect_err(state, f"Slack token exchange ok=false: {tok.get('error')}")

    # Slack v2 returns bot token in `access_token`, user token in
    # `authed_user.access_token`. We stash both — connectors/slack.py
    # prefers user token, falls back to bot.
    bot_token = tok.get("access_token") or ""
    user_id = pending["user_id"]
    existing = (await db.execute(
        select(OAuthToken).where(
            OAuthToken.user_id == user_id, OAuthToken.provider == "slack"
        )
    )).scalar_one_or_none()

    # Slack tokens generally don't expire — leave expires_at NULL.
    extra_json = {
        "authed_user": tok.get("authed_user") or {},
        "team": tok.get("team") or {},
        "scope": tok.get("scope"),
    }

    if existing:
        existing.access_token = bot_token
        existing.token_type = "Bearer"
        existing.scope = tok.get("scope")
        existing.extra_json = extra_json
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(OAuthToken(
            user_id=user_id,
            provider="slack",
            access_token=bot_token,
            token_type="Bearer",
            scope=tok.get("scope"),
            extra_json=extra_json,
        ))
    await db.commit()

    return RedirectResponse(url=pending["client_redirect"], status_code=302)


def _redirect_err(state: str | None, message: str) -> RedirectResponse:
    target = "uxie://oauth/slack/error"
    pending = _PENDING.pop(state, None) if state else None
    if pending and pending.get("client_redirect"):
        target = pending["client_redirect"].rstrip("/").replace("/done", "/error")
    return RedirectResponse(
        url=f"{target}?{urlencode({'message': message})}", status_code=302,
    )
