"""Meeting auto-detection — spawns the audio-tap binary in --watch mode
and translates its JSON window-presence events into engine-level
meeting detections.

Architecture:
    audio-tap --watch    →    stdout JSON lines    →    meeting_watcher.py
        polls SCShareableContent every 5s,
        emits meeting-window-{appeared,disappeared}
                                                    │
                                                    ▼
        creates a meetings.db row with synthetic
        calendar_event_id, fires meeting:detected
        broadcast → renderer notification + UI

The watcher only runs if the user has enabled auto-detection (default
off — see config.get_auto_detect_meetings()). Starting / stopping is
driven by the engine's lifespan + the settings toggle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("meeting_watcher")


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


_proc: asyncio.subprocess.Process | None = None
_pump_task: asyncio.Task | None = None
_stderr_task: asyncio.Task | None = None
_active_detector_keys: dict[str, int] = {}  # detector_key → meetings.id


def is_running() -> bool:
    return _proc is not None and _proc.returncode is None


async def start() -> dict:
    """Spawn the watcher subprocess. Idempotent."""
    global _proc, _pump_task, _stderr_task

    if is_running():
        return {"ok": True, "already_running": True}

    # Locate the audio-tap binary via the same helper audio_meeting uses.
    import audio_meeting
    binary = audio_meeting._find_tap_binary()
    if not binary:
        return {"error": "audio tap binary not found — re-install Uxie"}

    try:
        _proc = await asyncio.create_subprocess_exec(
            binary, "--watch",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        log.error(f"failed to spawn watcher: {e}")
        _proc = None
        return {"error": f"spawn failed: {e}"}

    _pump_task = asyncio.create_task(_pump_events())
    _stderr_task = asyncio.create_task(_drain_stderr())
    log.info(f"meeting_watcher: started ({binary} --watch)")
    return {"ok": True}


async def stop() -> dict:
    """Terminate the watcher subprocess + cleanup."""
    global _proc, _pump_task, _stderr_task

    if not is_running():
        return {"ok": True, "already_stopped": True}

    if _proc is not None:
        try:
            _proc.terminate()
        except ProcessLookupError:
            pass

    for t in (_pump_task, _stderr_task):
        if t is None:
            continue
        try:
            await asyncio.wait_for(t, timeout=1.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            t.cancel()
        except Exception as e:
            log.warning(f"watcher task cleanup: {e}")

    if _proc is not None and _proc.returncode is None:
        try:
            await asyncio.wait_for(_proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            _proc.kill()

    _proc = None
    _pump_task = None
    _stderr_task = None
    _active_detector_keys.clear()
    log.info("meeting_watcher: stopped")
    return {"ok": True}


async def _pump_events() -> None:
    """Read stdout line-by-line, parse JSON, route to handlers."""
    if _proc is None or _proc.stdout is None:
        return
    try:
        while True:
            line = await _proc.stdout.readline()
            if not line:
                log.info("watcher stdout EOF")
                return
            try:
                event = json.loads(line.decode("utf-8", errors="replace"))
            except Exception as e:
                log.warning(f"bad watcher line: {e}: {line[:120]!r}")
                continue
            kind = event.get("event")
            if kind == "meeting-window-appeared":
                await _on_appeared(event)
            elif kind == "meeting-window-disappeared":
                await _on_disappeared(event)
            elif kind == "watcher-ready":
                log.info("watcher ready")
            else:
                log.debug(f"unhandled watcher event: {kind}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"_pump_events error: {e}")


async def _drain_stderr() -> None:
    if _proc is None or _proc.stderr is None:
        return
    try:
        while True:
            line = await _proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                log.info(f"[watcher] {text}")
    except asyncio.CancelledError:
        return
    except Exception as e:
        log.warning(f"_drain_stderr error: {e}")


# ── Event handlers ────────────────────────────────────────────────────────────


async def _on_appeared(event: dict) -> None:
    """A meeting window just opened. Create a synthetic meeting row and
    fire meeting:detected so the notification + UI flow kicks in."""
    detector_key = event.get("detector_key")
    title = event.get("title") or "Meeting"
    app_bundle_id = event.get("app_bundle_id", "")
    if not detector_key:
        return
    if detector_key in _active_detector_keys:
        return  # dedupe — we already fired for this one

    import meetings
    now = int(time.time())
    # Reuse the existing meetings table. We treat the watcher's
    # detector_key as the row's calendar_event_id — shapes never collide
    # (Google IDs look like _60sj4c1q60o3acb5cdom2bb1c8; watcher keys
    # look like com.tinyspeck.slackmacgap#12345). The start/end are
    # synthetic since we don't know the meeting duration in advance.
    ev = {
        "calendar_event_id": detector_key,
        "title": title[:300],
        "start_ts": now,
        "end_ts": now + 60 * 60,   # 1h placeholder; can be revised on disappear
        "attendees": [],
        "meeting_url": "",
        "organizer": app_bundle_id,
    }
    try:
        db_id, _is_new = meetings._upsert_event(ev)
    except Exception as e:
        log.warning(f"watcher upsert failed: {e}")
        return

    _active_detector_keys[detector_key] = db_id

    # Hand off to the normal meeting:detected pipeline so the renderer
    # gets a notification + the Meetings tab refreshes.
    full = meetings.get_meeting(db_id) or {}
    await _emit("meeting:detected", full)
    log.info(f"watcher detected: title={title!r} db_id={db_id}")


async def _on_disappeared(event: dict) -> None:
    """A meeting window just closed. Update the end_ts. If the meeting
    is currently being recorded, we leave it running — the user
    explicitly clicked Record and owns Stop."""
    detector_key = event.get("detector_key")
    if not detector_key:
        return
    db_id = _active_detector_keys.pop(detector_key, None)
    if db_id is None:
        return

    import sqlite3
    import meetings
    now = int(time.time())
    try:
        with meetings._conn() as c:
            c.execute(
                "UPDATE meetings SET end_ts = ?, updated_at = ? WHERE id = ?",
                (now, now, db_id),
            )
    except sqlite3.Error as e:
        log.warning(f"watcher end_ts update failed: {e}")

    await _emit("meeting:window-closed", {"id": db_id, "detector_key": detector_key})
    log.info(f"watcher window closed: db_id={db_id}")
