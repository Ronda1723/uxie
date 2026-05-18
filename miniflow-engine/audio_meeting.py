"""Meeting audio capture pipeline.

Architecture:
    ┌───────────────────────────────────────┐
    │ UxieAudioTap.app (Swift sidecar)      │
    │   • AVCaptureSession   (mic)          │
    │   • ScreenCaptureKit   (system audio) │
    │   • mix → 16 kHz mono int16 PCM       │
    │   → stdout                            │
    └──────────────┬────────────────────────┘
                   │ raw PCM bytes
                   ▼
    ┌───────────────────────────────────────┐
    │ audio_meeting (this module)           │
    │   pumps stdout → Deepgram WS          │
    │   pumps DG finals → meeting transcript│
    └───────────────────────────────────────┘

The sidecar is shipped as `Uxie.app/Contents/Resources/UxieAudioTap.app/`
— a proper .app sub-bundle so its Info.plist's `NSMicrophoneUsageDescription`
+ `NSScreenCaptureDescription` are visible to TCC. Raw CLI binaries get
silently rejected by TCC; sub-bundle wrapping is the canonical fix.

Only ONE meeting can record at a time. `start_capture` while another is
active stops the previous one first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import ssl
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import certifi
import websockets

import config

log = logging.getLogger("audio_meeting")

# Reused per-call so PyInstaller bundles don't re-create the SSL context.
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Deepgram disconnects after ~10s of pure silence without a KeepAlive.
_KEEPALIVE_INTERVAL_SECONDS = 5.0

# Must match the Swift binary's output (FRAME_SAMPLES @ OUTPUT_SAMPLE_RATE).
_SAMPLE_RATE = 16_000


def _find_tap_binary() -> str | None:
    """Locate the audio-tap executable inside its .app sub-bundle.

    Packaged build: `Uxie.app/Contents/Resources/UxieAudioTap.app/Contents/MacOS/uxie-audio-tap`
    Dev:           `native-helper/audio-tap/.build/release/UxieAudioTap.app/Contents/MacOS/uxie-audio-tap`
    """
    if sys.platform != "darwin":
        return None

    candidates: list[Path] = []
    INNER = Path("UxieAudioTap.app") / "Contents" / "MacOS" / "uxie-audio-tap"

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass)
        for _ in range(4):
            candidates.append(p / INNER)
            p = p.parent

    candidates.append(
        Path(__file__).resolve().parent.parent
        / "native-helper" / "audio-tap" / ".build" / "release" / INNER
    )

    found = shutil.which("uxie-audio-tap")
    if found:
        candidates.append(Path(found))

    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return None


# ── Deepgram key (shared with audio.py's cache) ───────────────────────────────


async def _get_deepgram_key() -> str | None:
    """Reuse audio.py's cached + prewarmed key minter."""
    from audio import _get_deepgram_key as _get  # type: ignore
    return await _get()


# ── Module state ──────────────────────────────────────────────────────────────


_event_emitter: Callable[[str, Any], Awaitable[None]] | None = None


def set_event_emitter(fn: Callable[[str, Any], Awaitable[None]]) -> None:
    global _event_emitter
    _event_emitter = fn


async def _emit(event: str, payload: Any) -> None:
    if _event_emitter is None:
        return
    try:
        await _event_emitter(event, payload)
    except Exception as e:
        log.warning(f"emit({event}) failed: {e}")


_session: "_Session | None" = None
_session_lock = asyncio.Lock()


class _Session:
    """One active recording. Owns the tap subprocess + Deepgram socket +
    the asyncio tasks that move bytes between them."""
    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.proc: asyncio.subprocess.Process | None = None
        self.ws: Any = None
        self.tasks: list[asyncio.Task] = []
        self.stopped = False

    async def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True

        # 1. Tell Deepgram to flush. The receiver task will pick up the
        #    tail before exiting.
        if self.ws is not None:
            try: await self.ws.send(json.dumps({"type": "CloseStream"}))
            except Exception: pass

        # 2. SIGTERM the tap. Its stdin watcher also catches EOF when we
        #    later close the pipe, but SIGTERM is more decisive.
        if self.proc is not None and self.proc.returncode is None:
            try: self.proc.terminate()
            except ProcessLookupError: pass

        # 3. Give Deepgram up to 2s to deliver the final transcript.
        for t in self.tasks:
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()
            except Exception as e:
                log.warning(f"task cleanup error: {e}")

        # 4. Close everything.
        if self.ws is not None:
            try: await self.ws.close()
            except Exception: pass
        if self.proc is not None and self.proc.returncode is None:
            try: await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except asyncio.TimeoutError: self.proc.kill()


# ── Public API ────────────────────────────────────────────────────────────────


async def start_capture(meeting_id: int) -> dict:
    """Spawn the audio tap + open Deepgram. Returns {ok} or {error}.
    Idempotent — stops any prior session first."""
    global _session

    if sys.platform != "darwin":
        return {"error": "meeting recording is macOS-only"}

    binary = _find_tap_binary()
    if not binary:
        return {"error": "audio tap binary not found — re-install Uxie"}

    async with _session_lock:
        if _session is not None:
            await _session.stop()
            _session = None

        key = await _get_deepgram_key()
        if not key:
            return {"error": "not signed in — connect Uxie account first"}

        sess = _Session(meeting_id=meeting_id)
        _session = sess

        # 1. Spawn the tap subprocess. It writes PCM to stdout, diagnostics
        #    to stderr, and exits on stdin-EOF or SIGTERM.
        try:
            sess.proc = await asyncio.create_subprocess_exec(
                binary,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            log.error(f"failed to spawn audio tap: {e}")
            _session = None
            return {"error": f"could not spawn audio tap: {e}"}

        # 2. Open Deepgram long-form streaming socket.
        #    - diarize:true → speaker labels (Speaker 0/1/...)
        #    - smart_format + punctuate → readable output for the structure pass
        #    - interim_results:false → only persist finals (cheaper, simpler)
        #    - no endpointing close — the user owns Stop
        url = (
            f"wss://api.deepgram.com/v1/listen"
            f"?model=nova-3"
            f"&encoding=linear16&sample_rate={_SAMPLE_RATE}&channels=1&language=en-US"
            f"&punctuate=true&smart_format=true&diarize=true"
            f"&interim_results=false"
        )
        try:
            sess.ws = await websockets.connect(
                url,
                extra_headers={"Authorization": f"Token {key}"},
                ssl=_SSL_CTX,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            )
        except Exception as e:
            log.error(f"Deepgram connect failed: {e}")
            await sess.stop()
            _session = None
            return {"error": f"deepgram connect failed: {e}"}

        sess.tasks = [
            asyncio.create_task(_pump_tap_to_deepgram(sess)),
            asyncio.create_task(_pump_deepgram_transcripts(sess)),
            asyncio.create_task(_keepalive(sess)),
            asyncio.create_task(_drain_stderr(sess)),
        ]
        log.info(f"audio_meeting: started meeting_id={meeting_id} binary={binary}")
        return {"ok": True}


async def stop_capture() -> dict:
    """Stop the active session. Idempotent."""
    global _session
    async with _session_lock:
        if _session is None:
            return {"ok": True, "already_stopped": True}
        sess = _session
        _session = None
        await sess.stop()
        log.info(f"audio_meeting: stopped meeting_id={sess.meeting_id}")
        return {"ok": True}


def active_meeting_id() -> int | None:
    return _session.meeting_id if _session and not _session.stopped else None


# ── Pumps ─────────────────────────────────────────────────────────────────────


async def _pump_tap_to_deepgram(sess: _Session) -> None:
    """Read PCM bytes from the tap subprocess, forward to Deepgram. 4 KB
    ≈ 125 ms at 16 kHz mono int16 — small enough for low transcript
    latency, large enough to avoid syscall thrash."""
    assert sess.proc is not None and sess.proc.stdout is not None
    try:
        while not sess.stopped:
            data = await sess.proc.stdout.read(4096)
            if not data:
                log.info("audio_meeting: tap stdout EOF")
                break
            if sess.ws is not None:
                try:
                    await sess.ws.send(data)
                except websockets.exceptions.ConnectionClosed:
                    log.info("audio_meeting: Deepgram closed during send")
                    break
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"_pump_tap_to_deepgram error: {e}")


async def _pump_deepgram_transcripts(sess: _Session) -> None:
    """Each Deepgram `is_final` chunk → append to the meeting transcript +
    broadcast `meeting:transcript-update` so the renderer live-updates."""
    assert sess.ws is not None
    import meetings  # local import to dodge circular dependency
    try:
        async for msg in sess.ws:
            if sess.stopped:
                break
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
            appended = meetings.append_transcript_chunk(sess.meeting_id, transcript)
            await _emit("meeting:transcript-update", appended)
    except websockets.exceptions.ConnectionClosed:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"_pump_deepgram_transcripts error: {e}")


async def _keepalive(sess: _Session) -> None:
    """Send periodic KeepAlive so silent stretches (everyone muted,
    breakout rooms) don't time the socket out."""
    try:
        while not sess.stopped and sess.ws is not None:
            await asyncio.sleep(_KEEPALIVE_INTERVAL_SECONDS)
            if sess.stopped or sess.ws is None:
                return
            try:
                await sess.ws.send(json.dumps({"type": "KeepAlive"}))
            except Exception:
                return
    except asyncio.CancelledError:
        return


async def _drain_stderr(sess: _Session) -> None:
    """Surface tap stderr (mic format dumps, heartbeats, permission errors)
    into the engine log — invaluable when debugging in production."""
    if sess.proc is None or sess.proc.stderr is None:
        return
    try:
        while not sess.stopped:
            line = await sess.proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                log.info(f"[tap] {text}")
    except asyncio.CancelledError:
        return
    except Exception as e:
        log.warning(f"_drain_stderr error: {e}")
