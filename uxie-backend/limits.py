"""
Per-user, per-month usage limits.

Free tier (after 30-day trial):
  - 100 dictation corrections / month
  - 50 commands / month

Pro tier:
  - Unlimited dictation
  - 500 commands / month

During free_days_remaining > 0: full Pro limits apply (trial period).

In addition to the monthly counters above, expensive endpoints use the
`check_burst()` helper below for an in-memory per-hour + per-day token
bucket. This is defence-in-depth against a stolen JWT being used to burn
the bill in a single night.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import Usage, User
from settings import get_settings

_settings = get_settings()


# ── In-memory burst limiter (per-process; resets on restart) ──────────────────
# Maps (bucket_key, user_id) → deque of recent call timestamps. We trim and
# count in a single pass on every call. Sliding window, not fixed bucket, so
# users can't game the boundary by stacking calls right before/after the hour.

_burst: dict[tuple[str, int], deque[float]] = defaultdict(deque)


def check_burst(
    user_id: int,
    bucket: str,
    *,
    per_hour: int,
    per_day: int,
) -> None:
    """Raise 429 if `user_id` exceeded their per-hour or per-day quota for
    `bucket`. Trims expired timestamps in place so memory stays bounded."""
    now = time.time()
    hour_cutoff = now - 3600
    day_cutoff = now - 86400

    q = _burst[(bucket, user_id)]
    # Drop anything older than 24h.
    while q and q[0] < day_cutoff:
        q.popleft()

    # Count items inside the 1h window.
    recent_hour = sum(1 for t in q if t >= hour_cutoff)
    if recent_hour >= per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: max {per_hour} {bucket} requests/hour.",
        )
    if len(q) >= per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: max {per_day} {bucket} requests/day.",
        )
    q.append(now)


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _get_or_create_usage(db: AsyncSession, user_id: int, month: str) -> Usage:
    result = await db.execute(
        select(Usage).where(Usage.user_id == user_id, Usage.month == month)
    )
    usage = result.scalar_one_or_none()
    if not usage:
        usage = Usage(user_id=user_id, month=month)
        db.add(usage)
        await db.flush()
    return usage


async def check_and_increment(db: AsyncSession, user: User, action: str):
    """Check limit then increment. Raises 429 if over limit.

    action: "dictation" | "command"
    """
    month = _current_month()
    usage = await _get_or_create_usage(db, user.id, month)

    # Trial: full Pro access while free_days_remaining > 0
    on_trial = user.free_days_remaining > 0
    tier = "pro" if on_trial or user.tier == "pro" else "free"

    if action == "dictation":
        limit = (
            _settings.pro_dictation_limit if tier == "pro"
            else _settings.free_dictation_limit
        )
        if usage.dictation_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Monthly dictation limit ({limit}) reached. Upgrade to Pro.",
            )
        usage.dictation_count += 1
    elif action == "command":
        limit = (
            _settings.pro_command_limit if tier == "pro"
            else _settings.free_command_limit
        )
        if usage.command_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Monthly command limit ({limit}) reached. Upgrade to Pro.",
            )
        usage.command_count += 1
    else:
        raise ValueError(f"Unknown action: {action}")

    await db.commit()


async def get_usage_summary(db: AsyncSession, user: User) -> dict:
    month = _current_month()
    usage = await _get_or_create_usage(db, user.id, month)
    await db.commit()
    on_trial = user.free_days_remaining > 0
    tier = "pro" if on_trial or user.tier == "pro" else "free"
    return {
        "month": month,
        "tier": tier,
        "on_trial": on_trial,
        "free_days_remaining": user.free_days_remaining,
        "dictation": {
            "used": usage.dictation_count,
            "limit": _settings.pro_dictation_limit if tier == "pro" else _settings.free_dictation_limit,
        },
        "command": {
            "used": usage.command_count,
            "limit": _settings.pro_command_limit if tier == "pro" else _settings.free_command_limit,
        },
    }
