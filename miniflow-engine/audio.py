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
_session_id: str = ""                  # UUID generated per session; threaded through LLM calls + audio upload
_final_fragments: list[str] = []       # accumulates is_final transcripts
_latest_interim: str = ""              # most recent interim hypothesis (in-flight, not yet final)
_last_seen_received: asyncio.Event | None = None
_receive_task: asyncio.Task | None = None
_chunk_queue: list[bytes] = []         # buffers chunks received before socket connects
_connecting: bool = False
_captured_pcm: bytearray = bytearray() # full-session audio for admin debugging upload

# Meeting mode — when set, finalized Deepgram chunks get appended to this
# meeting's transcript instead of being collected for LLM dispatch.
_meeting_id: int | None = None
_meeting_ws = None
_meeting_recv_task: asyncio.Task | None = None
_meeting_keepalive_task: asyncio.Task | None = None


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


async def _upload_session_audio(session_id: str, pcm: bytes, sample_rate: int) -> None:
    """Upload the captured PCM to the backend's /debug/upload-audio. 503s are
    silently ignored (R2 not configured is fine — text logging still works)."""
    if not pcm or len(pcm) < 1000:  # <~30ms of audio — probably an aborted session
        return
    import config as _config
    jwt = _config.get_jwt()
    if not jwt:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_config.get_uxie_backend_url()}/debug/upload-audio",
                content=bytes(pcm),
                headers={
                    "Authorization": f"Bearer {jwt}",
                    "Content-Type": "application/octet-stream",
                    "X-Session-Id": session_id,
                    "X-Sample-Rate": str(sample_rate),
                },
            )
            if resp.status_code == 503:
                return  # R2 not configured on backend; expected in dev
            if resp.status_code >= 400:
                log.warning(f"audio upload failed: {resp.status_code} {resp.text[:200]}")
            else:
                log.info(f"audio uploaded: session={session_id[:8]}... bytes={len(pcm)}")
    except Exception as e:
        log.warning(f"audio upload exception: {e}")


async def start_listening(sample_rate: int = 16000, mode: str = "dictation"):
    global _dg_ws, _sample_rate, _final_fragments, _latest_interim, _session_active, _session_mode
    global _last_seen_received, _receive_task, _chunk_queue, _connecting
    global _session_id, _captured_pcm
    import uuid as _uuid
    _sample_rate = sample_rate
    _final_fragments = []
    _latest_interim = ""
    _chunk_queue = []
    _captured_pcm = bytearray()
    _session_id = _uuid.uuid4().hex
    _connecting = True
    _session_active = True
    _session_mode = mode if mode in ("dictation", "command") else "dictation"
    _last_seen_received = asyncio.Event()
    log.info(f"Starting listening session: mode={_session_mode} session_id={_session_id}")

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
        f"?model=nova-3"
        f"&encoding=linear16&sample_rate={sample_rate}&language=en-US"
        f"&punctuate=true&numerals=true&smart_format=true"
        f"&interim_results=true&endpointing=200"
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
    # Always tap a copy for admin audio debugging. This is a no-op when R2
    # isn't configured on the backend (upload is skipped at session end).
    _captured_pcm.extend(decoded)
    # During a meeting we fan out to BOTH the dictation socket (if a
    # hotkey press happens to overlap) and the meeting socket. In
    # practice users won't hotkey-dictate during a meeting, but the
    # routing being independent keeps each path simple.
    if _meeting_ws is not None:
        try:
            await _meeting_ws.send(decoded)
        except Exception as e:
            log.warning(f"send_audio_chunk (meeting): {e}")
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

    # Short grace window for a speech_final that may already be in-flight. We
    # intentionally don't block users on Deepgram's endpointing — they released
    # the hotkey, they want the result NOW. If nothing finalizes in 300ms we
    # proceed with the latest interim hypothesis.
    try:
        assert _last_seen_received is not None
        await asyncio.wait_for(_last_seen_received.wait(), timeout=0.3)
    except asyncio.TimeoutError:
        pass

    # Prefer committed finals; fall back to the most recent interim for the tail
    # Deepgram hasn't yet finalized. Interim hypotheses from Nova-3 are usually
    # within a word of the final transcript on short utterances.
    finals_text = _consolidate_fragments(_final_fragments)
    if _latest_interim and _latest_interim not in finals_text:
        raw_text = (finals_text + " " + _latest_interim).strip() if finals_text else _latest_interim
    else:
        raw_text = finals_text

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
        # Upload captured audio to the admin debug bucket in the background so
        # we can replay what Deepgram heard when transcripts look wrong. Safe
        # no-op when the backend's R2 env vars aren't set.
        try:
            asyncio.create_task(_upload_session_audio(_session_id, bytes(_captured_pcm), _sample_rate))
        except Exception as e:
            log.warning(f"schedule audio upload failed: {e}")


# ── Internal ──────────────────────────────────────────────────────────────────

async def _receive_transcripts():
    """Drain Deepgram messages. Keep is_final transcripts; signal on speech_final or close."""
    global _latest_interim
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
                    _latest_interim = ""   # finalized segment consumed the interim
                elif transcript:
                    # Interim hypothesis — stream to UI for live popover display.
                    _latest_interim = transcript
                    await _emit("transcription-interim", {"transcript": transcript})
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


# ── Meeting (long-form) capture ───────────────────────────────────────────────
# Reuses the renderer's existing mic capture path. The renderer fires
# `voice:chunk` IPC for every 100ms PCM chunk; send_audio_chunk above
# fans those out to the meeting WebSocket when one is open. Finalized
# transcripts get appended to the meeting's row in SQLite.


async def start_meeting_listening(meeting_id: int) -> dict:
    """Open a long-form Deepgram socket for a meeting. Idempotent —
    calling while another meeting is recording stops it first."""
    global _meeting_id, _meeting_ws, _meeting_recv_task, _meeting_keepalive_task

    if _meeting_ws is not None:
        await stop_meeting_listening()

    key = await _get_deepgram_key()
    if not key:
        return {"error": "Not signed in — connect Uxie account first"}

    # diarize=true → speaker labels (Speaker 0/1/…) for multi-party calls.
    # smart_format + punctuate → readable output for the structure pass.
    # interim_results=false → we only persist finals (cheaper, simpler).
    # No endpointing close — the user explicitly clicks Stop.
    url = (
        f"wss://api.deepgram.com/v1/listen"
        f"?model=nova-3"
        f"&encoding=linear16&sample_rate=16000&channels=1&language=en-US"
        f"&punctuate=true&smart_format=true&diarize=true"
        f"&interim_results=false"
    )
    try:
        _meeting_ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {key}"},
            ssl=_SSL_CTX,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
    except Exception as e:
        log.error(f"start_meeting_listening: Deepgram connect failed: {e}")
        _meeting_ws = None
        return {"error": f"deepgram connect failed: {e}"}

    _meeting_id = int(meeting_id)
    _meeting_recv_task = asyncio.create_task(_meeting_receive())
    _meeting_keepalive_task = asyncio.create_task(_meeting_keepalive())
    log.info(f"meeting recording: started for meeting_id={meeting_id}")
    return {"ok": True}


async def stop_meeting_listening() -> dict:
    """Close the meeting Deepgram socket and flush its tail. Safe to call
    when no meeting session is active."""
    global _meeting_id, _meeting_ws, _meeting_recv_task, _meeting_keepalive_task

    if _meeting_ws is None:
        return {"ok": True, "already_stopped": True}

    # Tell Deepgram to flush the final results.
    try:
        await _meeting_ws.send(json.dumps({"type": "CloseStream"}))
    except Exception:
        pass

    # Give Deepgram up to 1.5s to drain its tail before tearing down.
    if _meeting_recv_task is not None:
        try:
            await asyncio.wait_for(_meeting_recv_task, timeout=1.5)
        except asyncio.TimeoutError:
            _meeting_recv_task.cancel()
        except Exception:
            pass

    if _meeting_keepalive_task is not None:
        _meeting_keepalive_task.cancel()

    try:
        await _meeting_ws.close()
    except Exception:
        pass

    log.info(f"meeting recording: stopped for meeting_id={_meeting_id}")
    _meeting_id = None
    _meeting_ws = None
    _meeting_recv_task = None
    _meeting_keepalive_task = None
    return {"ok": True}


def meeting_is_active() -> bool:
    return _meeting_ws is not None


async def _meeting_receive() -> None:
    """Drain Deepgram messages. Each is_final transcript gets appended to
    the current meeting row + broadcast as `meeting:transcript-update`."""
    ws = _meeting_ws
    meeting_id = _meeting_id
    if ws is None or meeting_id is None:
        return
    try:
        async for msg in ws:
            if _meeting_ws is None:  # stopped concurrently
                return
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if data.get("type") != "Results":
                continue
            if not data.get("is_final"):
                continue
            alts = data.get("channel", {}).get("alternatives", [{}])
            transcript = (alts[0].get("transcript") or "").strip()
            if not transcript:
                continue
            try:
                import meetings as _meetings  # deferred to dodge import cycles
                appended = _meetings.append_transcript_chunk(meeting_id, transcript)
                await _emit("meeting:transcript-update", appended)
            except Exception as e:
                log.warning(f"meeting append_transcript_chunk failed: {e}")
    except websockets.exceptions.ConnectionClosed:
        return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"_meeting_receive error: {e}")


async def _meeting_keepalive() -> None:
    """Send Deepgram KeepAlive every 5s so silent stretches (everyone on
    mute, breakout rooms) don't time the socket out."""
    try:
        while _meeting_ws is not None:
            await asyncio.sleep(5.0)
            if _meeting_ws is None:
                return
            try:
                await _meeting_ws.send(json.dumps({"type": "KeepAlive"}))
            except Exception:
                return
    except asyncio.CancelledError:
        return


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
