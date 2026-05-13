"""Server-side connector token vending.

Mac and iOS clients never see provider client_secrets. They authenticate
to us with their Uxie JWT and we hand back a short-lived access_token
for the requested connector, refreshing the upstream token transparently
if it has expired.

Endpoint:
    GET /user/connector_token/{provider}
    Authorization: Bearer <uxie-jwt>

Response:
    200 { "access_token": "...", "expires_at": "2026-05-13T...Z", "scope": "..." }
    404 if the user hasn't connected that provider yet.
    502 if the upstream refresh failed.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import get_db
from db_ios import OAuthToken, User
from proxy import get_http
from settings import get_settings


# Buffer so callers get a token that's still good for at least this long.
# Google access tokens expire in ~1h; refreshing 60s early avoids the
# race where Mac receives an "almost-expired" token and Gmail rejects it
# mid-call.
_FRESH_THRESHOLD_SECONDS = 60


# ── Per-provider refresh logic ───────────────────────────────────────────────


async def _refresh_google(row: OAuthToken, db: AsyncSession) -> None:
    """Exchange the stored refresh_token for a new access_token."""
    if not row.refresh_token:
        raise HTTPException(409, "google token has no refresh_token; user must reconnect")
    settings = get_settings()
    client_id = (settings.google_client_id or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    client_secret = (settings.google_client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        raise HTTPException(500, "Google OAuth not configured on server")

    resp = await get_http().post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": row.refresh_token,
            "grant_type": "refresh_token",
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"Google refresh failed ({resp.status_code}): {resp.text[:200]}")
    tok = resp.json()

    row.access_token = tok["access_token"]
    if tok.get("refresh_token"):
        row.refresh_token = tok["refresh_token"]
    expires_in = int(tok.get("expires_in") or 3600)
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    row.updated_at = datetime.now(timezone.utc)
    if tok.get("scope"):
        row.scope = tok["scope"]
    await db.commit()


_REFRESH_HANDLERS = {
    "google": _refresh_google,
    # Slack: long-lived bot tokens, no refresh needed today. Add when we
    # start using rotating Slack tokens.
}


# ── HTTP endpoint ────────────────────────────────────────────────────────────


async def connector_token(
    provider: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row: Optional[OAuthToken] = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user.id,
                OAuthToken.provider == provider,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(404, f"{provider} not connected")

    # Refresh if we have an expiry and it's near or past.
    if row.expires_at is not None:
        now = datetime.now(timezone.utc)
        if row.expires_at - now <= timedelta(seconds=_FRESH_THRESHOLD_SECONDS):
            refresh = _REFRESH_HANDLERS.get(provider)
            if refresh:
                await refresh(row, db)
            # No handler? Fall through with whatever we have; the client
            # will fail and we can add a handler later.

    return {
        "access_token": row.access_token,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "scope": row.scope,
        "provider": provider,
    }
