"""Tests for referral code redemption and stats."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from db import User
from tests.conftest import _TestSessionLocal, create_user_and_token
import auth as auth_module


async def _register(client: AsyncClient, email: str, monkeypatch) -> tuple[str, str]:
    """Returns (token, referral_code)."""
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)
    token = await create_user_and_token(client, email)
    resp = await client.get("/user/status", headers={"Authorization": f"Bearer {token}"})
    code = resp.json()["referral_code"]
    return token, code


@pytest.mark.asyncio
async def test_referral_stats_empty(client: AsyncClient, monkeypatch):
    token, _ = await _register(client, "ref_stats@example.com", monkeypatch)
    resp = await client.get("/referral/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["friends_joined"] == 0
    assert data["days_earned"] == 0


@pytest.mark.asyncio
async def test_successful_referral(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)

    # Create referrer
    referrer_token, ref_code = await _register(client, "referrer@example.com", monkeypatch)

    # Create new user (referee)
    referee_token = await create_user_and_token(client, "referee@example.com")

    initial_days_resp = await client.get(
        "/user/status", headers={"Authorization": f"Bearer {referee_token}"}
    )
    initial_days = initial_days_resp.json()["free_days_remaining"]

    # Referee redeems referrer's code
    resp = await client.post(
        "/referral/redeem",
        json={"code": ref_code},
        headers={"Authorization": f"Bearer {referee_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["days_added"] == 30
    assert data["your_free_days"] == initial_days + 30

    # Referrer stats updated
    stats = await client.get("/referral/stats", headers={"Authorization": f"Bearer {referrer_token}"})
    assert stats.json()["friends_joined"] == 1
    assert stats.json()["days_earned"] == 30


@pytest.mark.asyncio
async def test_cannot_redeem_own_code(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)
    token, ref_code = await _register(client, "self_refer@example.com", monkeypatch)
    resp = await client.post(
        "/referral/redeem",
        json={"code": ref_code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cannot_redeem_twice(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)

    ref_token, ref_code = await _register(client, "referrer2@example.com", monkeypatch)
    ref_token2, ref_code2 = await _register(client, "referrer3@example.com", monkeypatch)
    user_token = await create_user_and_token(client, "greedy@example.com")

    # First redeem succeeds
    r1 = await client.post(
        "/referral/redeem",
        json={"code": ref_code},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r1.status_code == 200

    # Second redeem fails
    r2 = await client.post(
        "/referral/redeem",
        json={"code": ref_code2},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_invalid_referral_code(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(auth_module, "_send_email", lambda *a: None)
    token = await create_user_and_token(client, "invalid_ref@example.com")
    resp = await client.post(
        "/referral/redeem",
        json={"code": "NOSUCHCODE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
