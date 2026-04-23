"""
Audio — non-streaming STT pipeline (Deepgram).

Lifecycle:
    1. start_listening(mode)  → open Deepgram WebSocket, reset buffers
    2. send_audio_chunk(b64)  → forward PCM to Deepgram as it arrives
    3. stop_listening()       → send CloseStream, wait for final transcript,
                                 then run it through the LLM before emitting.

Design choice: we do NOT emit interim transcripts to the UI. We only emit ONE
`transcription` event at the end with the final, de-duplicated, LLM-cleaned text.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import ssl
import time
from typing import Callable

import certifi
import websockets

import config

log = logging.getLogger("audio")

# Single SSL context reused per session — certifi-backed so the PyInstaller
# bundle can verify Smallest AI's certificate.
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

_broadcaster: Callable | None = None
_dg_ws = None                          # Deepgram WebSocket
_sample_rate = 16000
_session_active = False
_session_mode: str = "dictation"
_final_fragments: list[str] = []       # accumulates is_final transcripts
_last_seen_received: asyncio.Event | None = None
_receive_task: asyncio.Task | None = None
_chunk_queue: list[bytes] = []         # buffers chunks received before socket connects
_connecting: bool = False


def set_event_broadcaster(fn: Callable):
    global _broadcaster
    _broadcaster = fn


async def _emit(event: str, payload):
    if _broadcaster:
        await _broadcaster(event, payload)


# ── Public API ────────────────────────────────────────────────────────────────

# Cached Deepgram ephemeral key. The backend mints a 5-min scoped key per call,
# so we reuse it across hotkey presses within its TTL to skip the ~300–800ms
# /stt/session round-trip. That round-trip delay is what caused the first word
# of an utterance to be dropped.
_cached_dg_key: str | None = None
_cached_dg_expires_at: float = 0.0
_cached_dg_lock: asyncio.Lock | None = None


async def _get_deepgram_key(force_refresh: bool = False) -> str | None:
    """Return a valid Deepgram key, refreshing from the backend only when near expiry."""
    global _cached_dg_key, _cached_dg_expires_at, _cached_dg_lock

    if _cached_dg_lock is None:
        _cached_dg_lock = asyncio.Lock()

    now = time.time()
    # Use the cached key if it's still fresh (>30s of headroom).
    if not force_refresh and _cached_dg_key and now < (_cached_dg_expires_at - 30):
        return _cached_dg_key

    async with _cached_dg_lock:
        # Recheck after acquiring the lock — another caller may have refreshed.
        now = time.time()
        if not force_refresh and _cached_dg_key and now < (_cached_dg_expires_at - 30):
            return _cached_dg_key

        import config as _config
        jwt = _config.get_jwt()
        if not jwt:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_config.get_uxie_backend_url()}/stt/session",
                    headers={"Authorization": f"Bearer {jwt}"},
                )
                resp.raise_for_status()
                data = resp.json()
            key = data.get("token")
            ttl = int(data.get("expires_in", 300))
            if key:
                _cached_dg_key = key
                _cached_dg_expires_at = time.time() + ttl
                log.info(f"Cached Deepgram key prefix={key[:8]}... ttl={ttl}s")
            return key
        except Exception as e:
            log.error(f"Failed to fetch STT token from backend: {e}")
            return None


async def prewarm_deepgram_key() -> None:
    """Fire-and-forget: fetch a key at engine startup so the first hotkey press is warm."""
    try:
        await _get_deepgram_key()
    except Exception as e:
        log.warning(f"prewarm_deepgram_key failed: {e}")


async def start_listening(sample_rate: int = 16000, mode: str = "dictation"):
    global _dg_ws, _sample_rate, _final_fragments, _session_active, _session_mode
    global _last_seen_received, _receive_task, _chunk_queue, _connecting
    _sample_rate = sample_rate
    _final_fragments = []
    _chunk_queue = []
    _connecting = True
    _session_active = True
    _session_mode = mode if mode in ("dictation", "command") else "dictation"
    _last_seen_received = asyncio.Event()
    log.info(f"Starting listening session: mode={_session_mode}")

    # Capture selected text NOW so transform commands have the selection available.
    if _session_mode == "command":
        import agent as _agent
        _agent.capture_selected_text()

    key = await _get_deepgram_key()
    if not key:
        _connecting = False
        await _emit("transcription-error", "Not signed in to Uxie. Please sign in from Settings.")
        return
    log.info(f"Deepgram key prefix: {key[:8]}... (len={len(key)})")

    url = (
        f"wss://api.deepgram.com/v1/listen"
        f"?encoding=linear16&sample_rate={sample_rate}&language=en-US"
        f"&punctuate=true&numerals=true&smart_format=true"
        f"&interim_results=false&endpointing=300"
    )
    try:
        _dg_ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {key}"},
            ssl=_SSL_CTX,
        )
    except Exception as e:
        # The cached key may have been revoked or expired; refresh once and retry.
        log.warning(f"Deepgram connect failed ({e}); refreshing key and retrying")
        key = await _get_deepgram_key(force_refresh=True)
        if not key:
            _connecting = False
            await _emit("transcription-error", f"Could not connect to Deepgram: {e}")
            return
        try:
            _dg_ws = await websockets.connect(
                url,
                extra_headers={"Authorization": f"Token {key}"},
                ssl=_SSL_CTX,
            )
        except Exception as e2:
            log.error(f"Deepgram connect failed on retry: {e2}")
            _connecting = False
            await _emit("transcription-error", f"Could not connect to Deepgram: {e2}")
            return

    # Flush any chunks that arrived while we were connecting
    if _chunk_queue:
        log.info(f"Flushing {len(_chunk_queue)} queued chunks to Deepgram")
        for queued in _chunk_queue:
            try:
                await _dg_ws.send(queued)
            except Exception as e:
                log.error(f"flush queued chunk: {e}")
                break
        _chunk_queue.clear()
    _connecting = False

    _receive_task = asyncio.create_task(_receive_transcripts())
    log.info(f"Deepgram connected (sample_rate={sample_rate})")


async def send_audio_chunk(chunk: str):
    decoded = base64.b64decode(chunk)
    if _connecting:
        _chunk_queue.append(decoded)
        return
    if _dg_ws:
        try:
            await _dg_ws.send(decoded)
        except Exception as e:
            log.error(f"send_audio_chunk: {e}")


async def stop_listening():
    """Close the Deepgram session, grab the final transcript, run through LLM."""
    global _dg_ws, _session_active, _receive_task
    if not _dg_ws:
        log.info("stop_listening: no active session")
        return

    await _emit("agent-status", "processing")

    # Tell Deepgram we're done sending audio
    try:
        await _dg_ws.send(json.dumps({"type": "CloseStream"}))
    except Exception as e:
        log.warning(f"Could not send CloseStream: {e}")

    # Wait up to 2.5s for Deepgram's final speech_final transcript
    try:
        assert _last_seen_received is not None
        await asyncio.wait_for(_last_seen_received.wait(), timeout=2.5)
    except asyncio.TimeoutError:
        log.warning("Timed out waiting for Deepgram final (2.5s); proceeding with what we have")

    raw_text = _consolidate_fragments(_final_fragments)

    ws_to_close = _dg_ws
    task_to_cancel = _receive_task
    _dg_ws = None
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
    log.info(f"Deepgram final raw ({len(_final_fragments)} fragments): '{raw_text[:120]}'")
    import agent as _agent
    await _emit("debug", {
        "type": "stt",
        "text": raw_text or "(empty)",
        "app": _agent._target_bundle_id or "unknown",
    })

    # Apply symbol normalization (email/URL spoken words → symbols),
    # then user dictionary substitutions, then snippet expansions —
    # all BEFORE the LLM pass so grammar correction sees clean text.
    import normalize, dictionary, snippets
    raw_text = normalize.apply(raw_text)
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
    """Drain Deepgram messages. Keep is_final transcripts; signal on speech_final or close."""
    try:
        assert _dg_ws is not None
        async for msg in _dg_ws:
            try:
                data = json.loads(msg)
            except Exception:
                continue

            msg_type = data.get("type", "")

            # Final transcript for a completed utterance
            if msg_type == "Results":
                channel = data.get("channel", {})
                alts = channel.get("alternatives", [{}])
                transcript = (alts[0].get("transcript") or "").strip()
                is_final = bool(data.get("is_final", False))
                speech_final = bool(data.get("speech_final", False))
                log.debug(f"Deepgram | is_final={is_final} speech_final={speech_final} | '{transcript}'")
                if is_final and transcript:
                    _final_fragments.append(transcript)
                if speech_final and _last_seen_received:
                    _last_seen_received.set()

            # Deepgram sends this when the stream is fully closed
            elif msg_type in ("Metadata", "SpeechStarted"):
                pass  # ignore metadata events

            elif msg_type == "CloseStream" or data.get("created"):
                if _last_seen_received:
                    _last_seen_received.set()
                break

    except websockets.exceptions.ConnectionClosed:
        if _last_seen_received:
            _last_seen_received.set()
    except Exception as e:
        log.error(f"Deepgram receive error: {e}")
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
