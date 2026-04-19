"""
Audio — non-streaming STT pipeline.

Lifecycle:
    1. start_listening(mode)  → open Waves WebSocket, reset buffers
    2. send_audio_chunk(b64)  → forward PCM to Waves as it arrives
    3. stop_listening()       → send "finalize" to Waves, wait for the final
                                 full transcript, then run it through the LLM
                                 (grammar-correct or full agent) before
                                 emitting anything to the UI.

Design choice: we do NOT emit interim transcripts to the UI. Waves streams
partial results at typing speed; showing them live produces the "jumpy, broken"
output the user noticed. We only emit ONE `transcription` event at the end
with the final, de-duplicated, LLM-cleaned text.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import ssl
from typing import Callable

import certifi
import websockets

import config

log = logging.getLogger("audio")

# Single SSL context reused per session — certifi-backed so the PyInstaller
# bundle can verify Smallest AI's certificate.
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

_broadcaster: Callable | None = None
_waves_ws = None
_sample_rate = 16000
_session_active = False
_session_mode: str = "dictation"
_final_fragments: list[str] = []  # accumulates per-utterance finals from Waves
_last_seen_received: asyncio.Event | None = None
_receive_task: asyncio.Task | None = None


def set_event_broadcaster(fn: Callable):
    global _broadcaster
    _broadcaster = fn


async def _emit(event: str, payload):
    if _broadcaster:
        await _broadcaster(event, payload)


# ── Public API ────────────────────────────────────────────────────────────────

async def _fetch_stt_token() -> str | None:
    """Fetch a short-lived Waves session token from the Uxie backend.
    Returns None if no JWT is stored (user not signed in)."""
    jwt = config.get_jwt()
    if not jwt:
        return None
    try:
        import httpx
        base = config.get_uxie_backend_url()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{base}/stt/session",
                headers={"Authorization": f"Bearer {jwt}"},
            )
            resp.raise_for_status()
            return resp.json().get("token")
    except Exception as e:
        log.warning(f"Failed to fetch STT session token from Uxie backend: {e}")
        return None


async def start_listening(sample_rate: int = 16000, mode: str = "dictation"):
    global _waves_ws, _sample_rate, _final_fragments, _session_active, _session_mode
    global _last_seen_received, _receive_task
    _sample_rate = sample_rate
    _final_fragments = []
    _session_active = True
    _session_mode = mode if mode in ("dictation", "command") else "dictation"
    _last_seen_received = asyncio.Event()
    log.info(f"Starting listening session: mode={_session_mode}")

    # Try Uxie backend token first; fall back to locally-stored master key
    key = await _fetch_stt_token()
    if not key:
        try:
            key = config.get_smallest_key()
        except ValueError as e:
            await _emit("transcription-error", str(e))
            return

    url = (
        f"wss://api.smallest.ai/waves/v1/pulse/get_text"
        f"?encoding=linear16&sample_rate={sample_rate}&language=en"
        f"&word_timestamps=false&numerals=true"
    )
    try:
        _waves_ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Bearer {key}"},
            ssl=_SSL_CTX,
        )
    except Exception as e:
        log.error(f"Waves connect failed: {e}")
        await _emit("transcription-error", f"Could not connect to Smallest AI Waves: {e}")
        return
    _receive_task = asyncio.create_task(_receive_transcripts())
    log.info(f"Waves connected (sample_rate={sample_rate})")


async def send_audio_chunk(chunk: str):
    if _waves_ws:
        try:
            await _waves_ws.send(base64.b64decode(chunk))
        except Exception as e:
            log.error(f"send_audio_chunk: {e}")


async def stop_listening():
    """Finalize the Waves session, grab the final transcript, and run it through
    the LLM before emitting anything to the UI."""
    global _waves_ws, _session_active, _receive_task
    if not _waves_ws:
        log.info("stop_listening: no active session")
        return

    await _emit("agent-status", "processing")

    try:
        await _waves_ws.send(json.dumps({"type": "finalize"}))
    except Exception as e:
        log.warning(f"Could not send finalize: {e}")

    # Wait up to 150ms for Waves' is_last. Most finals arrive in 50–120ms
    # after finalize; cutting from 400ms saves ~250ms of dead time before
    # the LLM call starts.
    try:
        assert _last_seen_received is not None
        await asyncio.wait_for(_last_seen_received.wait(), timeout=0.15)
    except asyncio.TimeoutError:
        log.warning("Timed out waiting for is_last (150ms); proceeding with what we have")

    # Snapshot the transcript NOW so we can start the LLM immediately.
    raw_text = _consolidate_fragments(_final_fragments)

    # Close socket + cancel receive task in the background — don't block LLM start.
    ws_to_close = _waves_ws
    task_to_cancel = _receive_task
    _waves_ws = None
    _receive_task = None
    _session_active = False

    async def _cleanup():
        try:
            if ws_to_close:
                await ws_to_close.close()
        except Exception:
            pass
        if task_to_cancel:
            task_to_cancel.cancel()
    asyncio.create_task(_cleanup())
    log.info(f"Waves final raw ({len(_final_fragments)} fragments): '{raw_text[:120]}'")

    # Apply user dictionary (word substitutions) + snippets (trigger → expansion)
    # BEFORE the LLM pass so streaming grammar correction works on the already-
    # expanded text. No-op if both are empty.
    import dictionary, snippets
    raw_text = dictionary.apply(raw_text)
    raw_text = snippets.apply(raw_text)

    if not raw_text:
        log.info("No transcript captured; nothing to dispatch.")
        await _emit("agent-status", "idle")
        return

    # Hand off to the agent. The agent function is responsible for the LLM
    # pass (grammar correction or tool-calling) AND for emitting the final
    # `transcription` + `action-result` events that the UI consumes.
    import agent  # deferred: agent ↔ audio would circular-import otherwise
    try:
        if _session_mode == "command":
            await _emit("transcription", {"transcript": raw_text, "is_final": True, "is_session": True})
            await agent.execute_command(raw_text)
        else:
            # Stream grammar-corrected tokens: the native helper types each
            # chunk as it arrives from the LLM, so the user sees output
            # within ~200 ms instead of waiting for the full response.
            full = await agent.dictate_streaming(raw_text, emit=_emit)
            import history
            history.append_entry(
                transcript=raw_text, entry_type="dictation",
                actions=[{"action": "dictation", "success": True, "message": full}],
                success=True,
            )
    except Exception as e:
        log.error(f"Post-transcription handler failed: {e}")
        await _emit("action-result", {"action": "agent-error", "success": False, "message": str(e)})
    finally:
        await _emit("agent-status", "idle")


# ── Internal ──────────────────────────────────────────────────────────────────

async def _receive_transcripts():
    """Drain Waves messages. We keep only `is_final` transcripts and signal
    `_last_seen_received` when `is_last` arrives so stop_listening can proceed."""
    try:
        assert _waves_ws is not None
        async for msg in _waves_ws:
            try:
                data = json.loads(msg)
            except Exception:
                continue
            transcript = (data.get("transcript") or "").strip()
            is_final = bool(data.get("is_final", False))
            is_last = bool(data.get("is_last", False))
            log.debug(f"Waves | is_final={is_final} is_last={is_last} | '{transcript}'")
            if is_final and transcript:
                _final_fragments.append(transcript)
            if is_last:
                if _last_seen_received:
                    _last_seen_received.set()
                break
    except websockets.exceptions.ConnectionClosed:
        if _last_seen_received:
            _last_seen_received.set()
    except Exception as e:
        log.error(f"Waves receive error: {e}")
        if _last_seen_received:
            _last_seen_received.set()


def _consolidate_fragments(fragments: list[str]) -> str:
    """Join `is_final` fragments and collapse obvious overlap.

    Some STT backends re-emit a final for each utterance; the tails of
    consecutive fragments sometimes repeat the head of the next one. Strip
    that overlap before joining."""
    out = ""
    for f in fragments:
        f = f.strip()
        if not f:
            continue
        if not out:
            out = f
            continue
        # Find the largest suffix of `out` that is a prefix of `f` (overlap).
        max_n = min(len(out), len(f))
        overlap = 0
        for n in range(max_n, 0, -1):
            if out.endswith(f[:n]):
                overlap = n
                break
        out = out + (" " if not out.endswith(" ") and not f[overlap:].startswith(" ") else "") + f[overlap:]
    return out.strip()
