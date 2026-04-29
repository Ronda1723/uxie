"""
Refresh-token rotation for iOS.

Why a separate module: keeps existing auth.py untouched. /auth/send-otp and
/auth/verify-otp continue to return exactly the same shape Mac/Windows expect.
This module ADDS:

  POST /auth/issue-refresh   — caller already has a valid access-token JWT;
                               server mints an opaque refresh_token (returned
                               once, stored as sha256 hash). Optional device_id.
  POST /auth/refresh         — exchange refresh_token → fresh access-token.
                               No JWT required (the refresh token IS the auth).

Mac/Windows ignore these endpoints entirely; their existing JWT lifetime stays
unchanged.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import _issue_jwt, current_user
from db import User, get_db
from db_ios import RefreshToken


REFRESH_TTL_DAYS = 30
ACCESS_TTL_S = 15 * 60  # mirrors /auth/verify-otp behavior; iOS treats this as authoritative


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Mint a new refresh token for the authenticated user.

    Body (optional): {"device_id": "<opaque-string>"}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    device_id = (body or {}).get("device_id")

    raw = secrets.token_urlsafe(32)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash(raw),
        device_id=device_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
    )
    db.add(rt)
    await db.commit()

    return {
        "refresh_token": raw,           # leaves the server exactly once
        "expires_in": REFRESH_TTL_DAYS * 86400,
    }


async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh-token for a fresh access-token.

    Body: {"refresh_token": "<opaque>"}
    """
    body = await request.json()
    raw = (body or {}).get("refresh_token")
    if not raw:
        raise HTTPException(400, "refresh_token required")

    h = _hash(raw)
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == h,
        RefreshToken.revoked == False,  # noqa: E712 — SQLAlchemy needs ==
    )
    rt = (await db.execute(stmt)).scalar_one_or_none()
    if not rt:
        raise HTTPException(401, "invalid refresh token")
    if rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "refresh token expired")

    user = await db.get(User, rt.user_id)
    if not user:
        raise HTTPException(401, "user not found")

    rt.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    access = _issue_jwt(user.id)
    return {"access_token": access, "expires_in": ACCESS_TTL_S}
