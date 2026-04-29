"""
iOS-related tables. Imports `Base` from db.py so models register with the same
metadata; importing this module before init_db() runs is enough to make
`Base.metadata.create_all` create the new tables.

Strictly additive — does NOT touch existing tables (users, otps, usage,
referrals, llm_usage, stt_usage, session_log).

Tables:
  conversations   — one per agent thread (cross-device for iOS, eventually desktop too)
  turns           — user / assistant / tool messages within a conversation
  agent_sessions  — currently-running agent loops (state: running | awaiting_* | done | error)
  refresh_tokens  — long-lived refresh tokens (iOS), opaque + sha256-hashed
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship

from db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)  # ULID-ish (timestamp + random)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)  # auto-derived from first user turn
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    last_active_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    turns = relationship("Turn", back_populates="conversation", cascade="all, delete-orphan", lazy="dynamic")


class Turn(Base):
    __tablename__ = "turns"

    id = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)        # "user" | "assistant" | "tool"
    text = Column(Text, nullable=True)
    tool_calls_json = Column(JSON, nullable=True)
    tool_call_id = Column(String, nullable=True)  # populated when role="tool"
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)

    conversation = relationship("Conversation", back_populates="turns")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    state = Column(String, nullable=False)  # running | awaiting_approval | awaiting_client_tool | done | error
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class RefreshToken(Base):
    """Opaque refresh tokens for iOS. The raw token leaves the server only once
    (in the response to /auth/issue-refresh); we store sha256(raw)."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    device_id = Column(String, nullable=True)  # client-supplied opaque ID
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
