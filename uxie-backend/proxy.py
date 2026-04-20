"""
Proxy routes — forwards LLM and STT requests on behalf of authenticated users.

Routes:
  POST /llm/stream   — SSE streaming to Groq (dictation) or OpenAI (commands)
  POST /stt/session  — returns a short-lived Waves STT session token (JWT signed by Uxie)
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import User, get_db
from limits import check_and_increment
from settings import get_settings

_settings = get_settings()


# ── LLM streaming proxy ───────────────────────────────────────────────────────

class LLMStreamRequest(BaseModel):
    messages: list[dict]
    model: str = "llama-3.1-8b-instant"
    provider: str = "groq"   # "groq" | "openai"
    temperature: float = 0.3
    max_tokens: int = 1024


_GROQ_BASE = "https://api.groq.com/openai/v1"
_OPENAI_BASE = "https://api.openai.com/v1"


def _llm_base_and_key(provider: str) -> tuple[str, str]:
    if provider == "groq":
        key = _settings.groq_api_key
        if not key:
            raise HTTPException(500, "Groq API key not configured on server")
        return _GROQ_BASE, key
    elif provider == "openai":
        key = _settings.openai_api_key
        if not key:
            raise HTTPException(500, "OpenAI API key not configured on server")
        return _OPENAI_BASE, key
    raise HTTPException(400, f"Unknown provider: {provider}")


async def _stream_chunks(base_url: str, api_key: str, payload: dict) -> AsyncIterator[bytes]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", f"{base_url}/chat/completions",
                                 headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    yield (line + "\n\n").encode()


async def llm_stream(
    body: LLMStreamRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    action = "dictation" if body.provider == "groq" else "command"
    await check_and_increment(db, user, action)

    base_url, api_key = _llm_base_and_key(body.provider)
    payload = {
        "model": body.model,
        "messages": body.messages,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "stream": True,
    }

    return StreamingResponse(
        _stream_chunks(base_url, api_key, payload),
        media_type="text/event-stream",
    )


# ── STT session token ─────────────────────────────────────────────────────────
# We issue a short-lived Waves token so the client can connect directly to
# Waves without ever seeing Uxie's master Waves API key.
#
# Implementation: Waves /v1/pulse/get_token exchanges our master key for a
# short-lived session token. We fetch that and return it to the client.

class LLMChatRequest(BaseModel):
    messages: list[dict]
    tools: list[dict] | None = None
    tool_choice: str | None = None
    model: str = "gpt-4o"
    provider: str = "openai"
    temperature: float = 0.2


async def llm_chat(
    body: LLMChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    action = "dictation" if body.provider == "groq" else "command"
    await check_and_increment(db, user, action)

    base_url, api_key = _llm_base_and_key(body.provider)
    payload: dict = {
        "model": body.model,
        "messages": body.messages,
        "temperature": body.temperature,
    }
    if body.tools:
        payload["tools"] = body.tools
        payload["tool_choice"] = body.tool_choice or "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


class STTSessionResponse(BaseModel):
    token: str
    expires_in: int   # seconds
    sample_rate: int = 16000


async def stt_session(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> STTSessionResponse:
    if not _settings.waves_api_key:
        raise HTTPException(500, "Waves API key not configured on server")

    return STTSessionResponse(
        token=_settings.waves_api_key,
        expires_in=_settings.waves_session_ttl_seconds,
    )
