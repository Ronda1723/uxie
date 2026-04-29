"""
iOS-facing server-side agent endpoints. Phase 0 scaffolding — protocol surface
is locked here so iOS can implement against it. Full LLM-tool-calling loop
ships in Phase 0.5 (next session).

Strictly additive: existing /llm/chat, /llm/stream, /stt/session keep working
exactly as before. Mac and Windows desktop clients are unaffected.

Endpoints (registered in main.py):
  POST /agent/execute                                    → SSE stream
  POST /agent/approve/{session_id}                       → resume on approval
  POST /agent/client_tool_result/{session_id}/{tcid}     → resume on client-tool result

SSE wire format (standard):
    event: tool_call_start
    data: {"id":"tc_abc","name":"send_slack","args":{...}}

Event taxonomy (frozen):
  session              — first event, includes session_id and conversation_id
  tool_call_start      — server-side tool dispatch begins
  tool_call_result     — server-side tool dispatch finished
  approval_needed      — destructive tool; client must POST /agent/approve
  client_tool_invoke   — LLM picked a client-only tool; client must POST result
  final_text           — user-visible final answer (free text, not a tool result)
  error                — terminal error (with code, message, retryable bool)
  done                 — clean stream end

Approval timeout: 60s. Client-tool timeout: 30s. Server keep-alive ping every
15s (": ping\\n\\n" SSE comment).

Known TODOs left for Phase 0.5:
  - Wire LLM tool-calling (reuse litellm machinery from proxy.py)
  - Persist Conversation/Turn rows as the loop progresses
  - Connector tools (Slack, Gmail, Calendar) — copy from miniflow-engine/connectors/
  - Multi-replica session storage (currently in-memory; needs Redis for prod scale)
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import User, get_db

_log = logging.getLogger("agent")


# ── Constants ─────────────────────────────────────────────────────────────────

APPROVAL_TIMEOUT_S = 60
CLIENT_TOOL_TIMEOUT_S = 30
KEEPALIVE_INTERVAL_S = 15

# Tools that always require user approval before executing.
DESTRUCTIVE_TOOLS: set[str] = {
    "send_slack", "send_email", "send_message",
    "create_calendar_event", "delete_calendar_event",
    "post_tweet", "create_issue", "delete_file",
}


# ── In-memory pending-gate state ──────────────────────────────────────────────
# Each parked agent loop registers an asyncio.Event keyed by an opaque gate-id.
# /agent/approve and /agent/client_tool_result look up the gate, store the
# client's response payload, and set the event to wake the loop.
#
# This is intentionally process-local for Phase 0. When we scale to multiple
# Railway replicas, swap _PENDING for a Redis pub/sub backplane keyed identically.

@dataclass
class _PendingGate:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    payload: dict[str, Any] | None = None


_PENDING: dict[str, _PendingGate] = {}
_PENDING_LOCK = asyncio.Lock()


async def _park(gate_id: str, timeout_s: float) -> dict[str, Any]:
    """Block until /agent/approve or /agent/client_tool_result fires `gate_id`.
    Returns the client's payload, or raises asyncio.TimeoutError."""
    gate = _PendingGate()
    async with _PENDING_LOCK:
        _PENDING[gate_id] = gate
    try:
        await asyncio.wait_for(gate.event.wait(), timeout=timeout_s)
        return gate.payload or {}
    finally:
        async with _PENDING_LOCK:
            _PENDING.pop(gate_id, None)


async def _wake(gate_id: str, payload: dict[str, Any]) -> bool:
    async with _PENDING_LOCK:
        gate = _PENDING.get(gate_id)
    if not gate:
        return False
    gate.payload = payload
    gate.event.set()
    return True


# ── SSE formatting ────────────────────────────────────────────────────────────

def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode("utf-8")


def _sse_ping() -> bytes:
    return b": ping\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def execute(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Run the server-side agent loop and stream events to the client.

    Request body (JSON):
        transcript: str                       — user's spoken text
        conversation_id: str | null           — null → start a new thread
        tools_available_on_client: [str]      — names of tools the client can run
        mode: "command" | "dictation"         — command runs the loop, dictation just echoes corrected text
    """
    body = await request.json()
    transcript: str = (body.get("transcript") or "").strip()
    conversation_id: str = body.get("conversation_id") or _ulid()
    client_tools: list[str] = list(body.get("tools_available_on_client") or [])
    mode: str = body.get("mode") or "command"

    if not transcript:
        raise HTTPException(400, "transcript required")
    if mode not in ("command", "dictation"):
        raise HTTPException(400, "mode must be 'command' or 'dictation'")

    session_id = _ulid()
    _log.info(
        "agent.execute user=%s session=%s mode=%s conv=%s client_tools=%d transcript_len=%d",
        user.id, session_id, mode, conversation_id, len(client_tools), len(transcript),
    )

    return StreamingResponse(
        _run_loop(session_id, conversation_id, transcript, mode, client_tools, user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def approve(session_id: str, request: Request, user: User = Depends(current_user)):
    """Resume a parked agent loop with the user's approval decision.

    Body: {"approved": bool}
    """
    body = await request.json()
    approved = bool(body.get("approved", False))
    woke = await _wake(f"approve:{session_id}", {"approved": approved})
    if not woke:
        raise HTTPException(404, "session not awaiting approval (or expired)")
    return {"ok": True}


async def client_tool_result(
    session_id: str,
    tool_call_id: str,
    request: Request,
    user: User = Depends(current_user),
):
    """Resume a parked agent loop with a client-tool execution result.

    Body: {"result": <any> | null, "error": <str> | null}
    """
    body = await request.json()
    woke = await _wake(
        f"client_tool:{session_id}:{tool_call_id}",
        {"result": body.get("result"), "error": body.get("error")},
    )
    if not woke:
        raise HTTPException(404, "session not awaiting this tool result (or expired)")
    return {"ok": True}


# ── Loop body ─────────────────────────────────────────────────────────────────
# Phase 0: emits a deterministic stub stream so iOS can wire up its SSE consumer
# end-to-end. Phase 0.5 replaces _phase0_stub_stream with the real LLM loop.

async def _run_loop(
    session_id: str,
    conversation_id: str,
    transcript: str,
    mode: str,
    client_tools: list[str],
    user_id: int,
) -> AsyncIterator[bytes]:
    try:
        yield _sse("session", {"session_id": session_id, "conversation_id": conversation_id})

        async for chunk in _phase0_stub_stream(session_id, conversation_id, transcript, mode, client_tools):
            yield chunk

        yield _sse("done", {"conversation_id": conversation_id})

    except asyncio.CancelledError:
        _log.info("agent.execute session=%s cancelled by client", session_id)
        raise
    except Exception as e:  # noqa: BLE001 — terminal user-visible error
        _log.exception("agent.execute session=%s failed", session_id)
        yield _sse("error", {"code": "internal", "message": str(e), "retryable": False})


async def _phase0_stub_stream(
    session_id: str, conversation_id: str, transcript: str, mode: str, client_tools: list[str],
) -> AsyncIterator[bytes]:
    """Deterministic event sequence for iOS to verify SSE plumbing. Replace in Phase 0.5."""
    # Demonstrates the full event taxonomy iOS needs to handle.
    yield _sse("tool_call_start", {"id": "tc_phase0", "name": "echo", "args": {"transcript": transcript}})
    await asyncio.sleep(0.05)
    yield _sse("tool_call_result", {"id": "tc_phase0", "ok": True, "result": "(phase 0 stub)"})

    if mode == "command" and "open_url" in client_tools:
        # Demonstrate the client-tool roundtrip so iOS can implement against it.
        tcid = "tc_phase0_client"
        yield _sse("client_tool_invoke", {
            "session_id": session_id,
            "id": tcid,
            "name": "open_url",
            "args": {"url": "https://uxie.ai/"},
        })
        try:
            result = await _park(f"client_tool:{session_id}:{tcid}", CLIENT_TOOL_TIMEOUT_S)
            yield _sse("tool_call_result", {"id": tcid, "ok": result.get("error") is None, "result": result})
        except asyncio.TimeoutError:
            yield _sse("error", {"code": "client_tool_timeout", "message": f"no result after {CLIENT_TOOL_TIMEOUT_S}s", "retryable": True})
            return

    yield _sse("final_text", {
        "text": (
            f"You said: {transcript}\n\n"
            "(Phase 0 stub — full LLM loop ships in Phase 0.5. "
            "iOS can verify SSE consumption + client-tool roundtrip + history persistence "
            "against this stub.)"
        ),
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ulid() -> str:
    """ULID-ish: ms timestamp + 64 random bits, lexicographically sortable."""
    ts = int(time.time() * 1000).to_bytes(6, "big").hex()
    rnd = secrets.token_hex(8)
    return f"{ts}{rnd}"
