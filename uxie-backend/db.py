"""
Database models and async engine setup.

Tables:
  users    — registered users with tier and referral code
  otps     — short-lived 6-digit codes for email auth
  usage    — monthly per-user dictation/command counts
  referrals — referral code redemption log
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from settings import get_settings

_settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _async_db_url(url: str) -> str:
    url = url.strip()  # env vars can have trailing newlines
    # Railway provides postgresql:// — asyncpg needs postgresql+asyncpg://
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    # Railway DATABASE_URL uses psycopg2-style sslmode=require; asyncpg needs ssl=require
    url = url.replace("sslmode=require", "ssl=require")
    url = url.replace("sslmode=prefer", "ssl=prefer")
    url = url.replace("sslmode=disable", "ssl=False")
    return url


engine = create_async_engine(_async_db_url(_settings.database_url), echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    tier = Column(String, nullable=False, default="free")  # "free" | "pro"
    referral_code = Column(String, unique=True, nullable=False)
    free_days_remaining = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    usages = relationship("Usage", back_populates="user", lazy="dynamic")


class OTP(Base):
    __tablename__ = "otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, nullable=False, default=False)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_usage_user_month"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    month = Column(String(7), nullable=False)  # "YYYY-MM"
    dictation_count = Column(Integer, nullable=False, default=0)
    command_count = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="usages")


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    redeemed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_referral_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def get_db():
    async with SessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
