"""Meeting audio orchestrator — thin shim over audio.py.

The actual mic capture lives in the Electron renderer (web Audio API) and
streams PCM chunks to the engine via the existing /voice:chunk IPC path —
the same path the hotkey dictation flow uses. When a meeting is active,
`audio.send_audio_chunk` fans those chunks out to a long-form Deepgram
socket whose finals get appended to the meeting transcript.

System-audio capture (ScreenCaptureKit) was prototyped but is not yet
shipping — AVAudioEngine doesn't behave reliably outside an .app bundle
context and we didn't have time to iterate on it. Mic-only is enough to
make the end-to-end flow real today.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import audio


_event_emitter: Callable[[str, Any], Awaitable[None]] | None = None


def set_event_emitter(fn: Callable[[str, Any], Awaitable[None]]) -> None:
    """audio.py already has its own broadcaster set by main.py, so this
    is just a compatibility shim for any caller that targets us by name."""
    global _event_emitter
    _event_emitter = fn


async def start_capture(meeting_id: int) -> dict:
    return await audio.start_meeting_listening(meeting_id)


async def stop_capture() -> dict:
    return await audio.stop_meeting_listening()


def active_meeting_id() -> int | None:
    if not audio.meeting_is_active():
        return None
    return audio._meeting_id  # type: ignore[attr-defined]
