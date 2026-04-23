"""
Proxy routes — forwards LLM and STT requests on behalf of authenticated users.

Routes:
  POST /llm/stream   — SSE streaming to Groq (dictation) or OpenAI (commands)
  POST /llm/chat     — non-streaming chat with optional tool calling
  POST /stt/session  — mints a short-lived Deepgram key scoped to this user
"""

from __future__ import annotations

import logging
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
import usage

_settings = get_settings()
_log = logging.getLogger("proxy")


# ── Shared HTTP client (connection pool + TLS reuse) ──────────────────────────

_http: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )
    return _http


async def close_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


# ── LLM streaming proxy ───────────────────────────────────────────────────────

class LLMStreamRequest(BaseModel):
    messages: list[dict]
    model: str = "llama-3.1-8b-instant"
    provider: str = "groq"   # "groq" | "openai"
    temperature: float = 0.3
    max_tokens: int = 1024


_GROQ_BASE = "https://api.groq.com/openai/v1"
_OPENAI_BASE = "https://api.openai.com/v1"
_DEEPGRAM_BASE = "https://api.deepgram.com/v1"


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


async def _stream_chunks(
    base_url: str,
    api_key: str,
    payload: dict,
    *,
    on_usage: "callable | None" = None,
) -> AsyncIterator[bytes]:
    """Proxy SSE from provider -> client, and on the way through, extract the
    final `usage` chunk (prompt_tokens, completion_tokens) for billing."""
    import json as _json
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    client = get_http()
    async with client.stream("POST", f"{base_url}/chat/completions",
                             headers=headers, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            # OpenAI/Groq emit `data: {...}` lines; the final usage chunk
            # lives on a chunk whose choices array is empty and `usage` is set.
            if on_usage and line.startswith("data: "):
                body = line[6:].strip()
                if body and body != "[DONE]":
                    try:
                        obj = _json.loads(body)
                        u = obj.get("usage")
                        if isinstance(u, dict):
                            on_usage(u)
                    except Exception:
                        pass
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
        # Opt in to usage accounting on the final chunk; both OpenAI and Groq
        # respect this. Without it, `usage` comes back null.
        "stream_options": {"include_usage": True},
    }

    # Captured by the stream generator and persisted after the response body
    # is fully sent. Scoped dict avoids needing a closure ref.
    captured: dict = {"prompt_tokens": 0, "completion_tokens": 0, "started_at": 0.0}

    import time as _time
    captured["started_at"] = _time.perf_counter()

    def _on_usage(u: dict) -> None:
        captured["prompt_tokens"] = int(u.get("prompt_tokens", 0) or 0)
        captured["completion_tokens"] = int(u.get("completion_tokens", 0) or 0)

    async def _wrap():
        try:
            async for chunk in _stream_chunks(base_url, api_key, payload, on_usage=_on_usage):
                yield chunk
        finally:
            duration_ms = int((_time.perf_counter() - captured["started_at"]) * 1000)
            await usage.record_llm_usage(
                db,
                user_id=user.id,
                provider=body.provider,
                model=body.model,
                action=action,
                prompt_tokens=captured["prompt_tokens"],
                completion_tokens=captured["completion_tokens"],
                duration_ms=duration_ms,
            )

    return StreamingResponse(_wrap(), media_type="text/event-stream")


# ── LLM non-streaming (tool calling / commands) ───────────────────────────────

class LLMChatRequest(BaseModel):
    messages: list[dict]
    model: str = "gpt-4o"
    provider: str = "openai"
    temperature: float = 0.2
    tools: list[dict] | None = None
    tool_choice: str | None = None


async def llm_chat(
    body: LLMChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    import time as _time
    await check_and_increment(db, user, "command")
    base_url, api_key = _llm_base_and_key(body.provider)
    payload: dict = {
        "model": body.model,
        "messages": body.messages,
        "temperature": body.temperature,
    }
    if body.tools:
        payload["tools"] = body.tools
        payload["tool_choice"] = body.tool_choice or "auto"

    client = get_http()
    t0 = _time.perf_counter()
    resp = await client.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    duration_ms = int((_time.perf_counter() - t0) * 1000)

    u = data.get("usage") or {}
    await usage.record_llm_usage(
        db,
        user_id=user.id,
        provider=body.provider,
        model=body.model,
        action="command",
        prompt_tokens=int(u.get("prompt_tokens", 0) or 0),
        completion_tokens=int(u.get("completion_tokens", 0) or 0),
        duration_ms=duration_ms,
    )
    return data


# ── STT session token ─────────────────────────────────────────────────────────
# If DEEPGRAM_PROJECT_ID is set, mint a per-session scoped key with short TTL.
# Otherwise fall back to returning the master key (warn — legacy behavior).

class STTSessionResponse(BaseModel):
    token: str
    expires_in: int = 300
    sample_rate: int = 16000


async def _mint_deepgram_key(user_id: int) -> tuple[str | None, str | None]:
    """Returns (key, api_key_id). key is None on failure."""
    master = (_settings.deepgram_api_key or "").strip()
    project_id = (_settings.deepgram_project_id or "").strip()
    if not master or not project_id:
        return None, None
    try:
        client = get_http()
        resp = await client.post(
            f"{_DEEPGRAM_BASE}/projects/{project_id}/keys",
            headers={
                "Authorization": f"Token {master}",
                "Content-Type": "application/json",
            },
            json={
                "comment": f"uxie-user-{user_id}",
                "scopes": ["usage:write"],
                "time_to_live_in_seconds": _settings.deepgram_session_ttl_seconds,
                "tags": [f"user:{user_id}"],
            },
        )
        if resp.status_code in (200, 201):
            j = resp.json()
            return j.get("key"), j.get("api_key_id")
        _log.warning(
            "Deepgram key mint failed: %s %s", resp.status_code, resp.text[:200]
        )
        return None, None
    except Exception as e:
        _log.warning("Deepgram key mint exception: %s", e)
        return None, None


async def stt_session(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> STTSessionResponse:
    ephemeral, key_id = await _mint_deepgram_key(user.id)
    if ephemeral:
        await usage.record_stt_usage(db, user_id=user.id, deepgram_key_id=key_id)
        return STTSessionResponse(
            token=ephemeral,
            expires_in=_settings.deepgram_session_ttl_seconds,
        )

    master = (_settings.deepgram_api_key or "").strip()
    if not master:
        raise HTTPException(500, "Deepgram API key not configured on server")
    _log.warning(
        "Returning master Deepgram key to user %s — set DEEPGRAM_PROJECT_ID to enable ephemeral keys",
        user.id,
    )
    await usage.record_stt_usage(db, user_id=user.id, deepgram_key_id=None)
    return STTSessionResponse(token=master, expires_in=3600)
