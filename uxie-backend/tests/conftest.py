"""
Pytest fixtures — in-memory SQLite engine, test app, and auth helpers.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Generate a matched RSA keypair for the whole test session ─────────────────

_priv = rsa.generate_private_key(65537, 2048, default_backend())
_TEST_PRIVATE_KEY = _priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()
_TEST_PUBLIC_KEY = _priv.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

# Set env vars BEFORE importing any app module so pydantic-settings picks them up
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_PRIVATE_KEY"] = _TEST_PRIVATE_KEY
os.environ["JWT_PUBLIC_KEY"] = _TEST_PUBLIC_KEY
os.environ["RESEND_API_KEY"] = "test-resend-key"

# ── App imports (after env is set) ────────────────────────────────────────────

from db import Base, get_db  # noqa: E402
from main import app  # noqa: E402

# ── In-memory DB engine ───────────────────────────────────────────────────────

_TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_TestSessionLocal = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False, class_=AsyncSession)


async def _override_get_db():
    async with _TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture()
async def db_session():
    async with _TestSessionLocal() as s:
        yield s


# ── Auth helper ───────────────────────────────────────────────────────────────

async def create_user_and_token(client: AsyncClient, email: str) -> str:
    """Register via OTP flow (Resend mocked) and return the JWT."""
    import auth as auth_module
    from sqlalchemy import select
    from db import OTP

    # Patch _send_email to no-op for this call
    original = auth_module._send_email
    auth_module._send_email = _noop_send_email

    try:
        resp = await client.post("/auth/send-otp", json={"email": email})
        assert resp.status_code == 200, resp.text
    finally:
        auth_module._send_email = original

    async with _TestSessionLocal() as s:
        result = await s.execute(
            select(OTP).where(OTP.email == email, OTP.used == False)
        )
        otp = result.scalars().first()
        assert otp, f"No OTP found for {email}"
        code = otp.code

    resp = await client.post("/auth/verify-otp", json={"email": email, "code": code})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _noop_send_email(to: str, code: str):
    pass
