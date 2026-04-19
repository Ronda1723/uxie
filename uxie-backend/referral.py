"""
Referral system.

- Every user has a unique referral_code generated at registration.
- Redeeming a code credits both referrer and new user +30 free days.
- A code can only be redeemed once per new user (at first login).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import Referral, User, get_db
from settings import get_settings

_settings = get_settings()
_REWARD_DAYS = 30


class RedeemRequest(BaseModel):
    code: str


async def redeem_referral(
    body: RedeemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Apply a referral code on behalf of the authenticated user.

    - The code must exist and belong to a different user.
    - The current user must not have redeemed any code before.
    - Both referrer and referee get +30 free days.
    """
    # Check the new user hasn't redeemed before
    already = await db.execute(
        select(Referral).where(Referral.redeemed_by == user.id)
    )
    if already.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="You have already redeemed a referral code.")

    # Find the referrer
    result = await db.execute(select(User).where(User.referral_code == body.code))
    referrer = result.scalar_one_or_none()
    if not referrer:
        raise HTTPException(status_code=404, detail="Referral code not found.")
    if referrer.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot redeem your own referral code.")

    # Record redemption
    log = Referral(
        code=body.code,
        referrer_id=referrer.id,
        redeemed_by=user.id,
        redeemed_at=datetime.now(timezone.utc),
    )
    db.add(log)

    # Credit both parties
    referrer.free_days_remaining += _REWARD_DAYS
    user.free_days_remaining += _REWARD_DAYS

    await db.commit()
    return {
        "detail": "Referral applied",
        "days_added": _REWARD_DAYS,
        "your_free_days": user.free_days_remaining,
    }


async def get_referral_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    result = await db.execute(
        select(Referral).where(Referral.referrer_id == user.id, Referral.redeemed_by != None)
    )
    redeemed = result.scalars().all()
    friends_joined = len(redeemed)
    days_earned = friends_joined * _REWARD_DAYS
    return {
        "referral_code": user.referral_code,
        "referral_link": f"https://uxie.ai/r/{user.referral_code}",
        "friends_joined": friends_joined,
        "days_earned": days_earned,
        "free_days_remaining": user.free_days_remaining,
    }
