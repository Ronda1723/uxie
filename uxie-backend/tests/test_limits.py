"""Tests for usage limits and tier enforcement."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from db import Usage, User
from tests.conftest import _TestSessionLocal, create_user_and_token
import auth as auth_module


async def _register(client: AsyncClient, email: str, monkeypatch) -> str:
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)
    return await create_user_and_token(client, email)


@pytest.mark.asyncio
async def test_user_status_shape(client: AsyncClient, monkeypatch):
    token = await _register(client, "limits_user1@example.com", monkeypatch)
    resp = await client.get("/user/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "dictation" in data
    assert "command" in data
    assert data["on_trial"] is True
    assert data["free_days_remaining"] == 30


@pytest.mark.asyncio
async def test_trial_user_has_pro_limits(client: AsyncClient, monkeypatch):
    """Users with free_days_remaining > 0 should get Pro limits."""
    token = await _register(client, "trial_user@example.com", monkeypatch)
    resp = await client.get("/user/status", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    # Pro dictation limit is 999999
    assert data["dictation"]["limit"] == 999999


@pytest.mark.asyncio
async def test_free_user_has_lower_limits(client: AsyncClient, monkeypatch):
    """Users with free_days_remaining == 0 get free-tier limits."""
    token = await _register(client, "free_tier@example.com", monkeypatch)

    # Drain trial days
    async with _TestSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == "free_tier@example.com"))
        user = result.scalar_one()
        user.free_days_remaining = 0
        await s.commit()

    resp = await client.get("/user/status", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    assert data["dictation"]["limit"] == 100
    assert data["command"]["limit"] == 50
    assert data["on_trial"] is False


@pytest.mark.asyncio
async def test_increment_is_tracked(client: AsyncClient, monkeypatch):
    """Each /llm/stream call increments the appropriate counter."""
    # We can test the limits module directly without going through the proxy
    # (proxy requires real API keys). Import and call directly.
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)
    token = await create_user_and_token(client, "count_track@example.com")

    async with _TestSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == "count_track@example.com"))
        user = result.scalar_one()

        import limits
        from datetime import datetime, timezone
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        await limits.check_and_increment(s, user, "dictation")
        await limits.check_and_increment(s, user, "command")

        result2 = await s.execute(select(Usage).where(Usage.user_id == user.id, Usage.month == month))
        usage = result2.scalar_one()
        assert usage.dictation_count == 1
        assert usage.command_count == 1
