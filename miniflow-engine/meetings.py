"""Meetings — detect upcoming calendar events, store transcripts, structure
them via Railway.

Design:
  - SQLite at ~/miniflow/meetings.db.
  - Background poll task hits Google Calendar (primary cal) every 60s.
  - When an event is within the lead-in window (60s by default) and we
    haven't notified for it yet, emit `meeting:detected` so the Electron
    main process can fire a native macOS Notification.
  - Recording itself is wired separately (Slice 2 — Swift ScreenCaptureKit
    sidecar). Slice 1 just marks status="recording" / "ended" / "structured".

Privacy:
  - Raw audio NEVER hits this module; only transcripts (already text) do.
  - Transcripts stay on disk in SQLite; only sent over the wire when the
    user clicks "Structure this meeting".
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

import config
import oauth

log = logging.getLogger("meetings")

DB_PATH = Path.home() / "miniflow" / "meetings.db"

# How often we ask Google for upcoming events.
POLL_INTERVAL_SECONDS = 60
# How far ahead we look for events.
LOOKAHEAD_SECONDS = 2 * 60 * 60
# How close to the start time we fire the "starting soon" notification.
LEAD_IN_SECONDS = 60
# Soft cap so we don't spam users on a busy calendar.
MAX_EVENTS_PER_POLL = 20

# Status state machine:
#   detected → user dismisses → (terminal)
#   detected → user accepts → recording → ended → structured
_STATUSES = {"detected", "recording", "ended", "structured", "skipped"}


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_event_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    start_ts INTEGER NOT NULL,           -- epoch seconds
    end_ts INTEGER NOT NULL,
    attendees_json TEXT NOT NULL DEFAULT '[]',
    meeting_url TEXT NOT NULL DEFAULT '',
    organizer TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'detected',
    notified INTEGER NOT NULL DEFAULT 0, -- 1 once we've fired the notification
    transcript TEXT NOT NULL DEFAULT '',
    user_notes TEXT NOT NULL DEFAULT '',
    structured_notes TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meetings_start_ts ON meetings(start_ts DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


# ── Public API (sync, invoked via /invoke handlers) ───────────────────────────


def list_meetings(limit: int = 50) -> list[dict]:
    _init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM meetings ORDER BY start_ts DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_meeting(meeting_id: int) -> dict | None:
    _init_db()
    with _conn() as c:
        r = c.execute("SELECT * FROM meetings WHERE id = ?", (int(meeting_id),)).fetchone()
    return _row_to_dict(r) if r else None


def delete_meeting(meeting_id: int) -> dict:
    _init_db()
    with _conn() as c:
        c.execute("DELETE FROM meetings WHERE id = ?", (int(meeting_id),))
    # Also remove the WAV file if one exists for this meeting.
    try:
        import audio_meeting
        p = audio_meeting.audio_path_for(meeting_id)
        if p.exists():
            p.unlink()
    except Exception as e:
        log.warning(f"audio cleanup for meeting {meeting_id} failed: {e}")
    return {"ok": True}


def delete_all_meetings() -> dict:
    """Privacy nuke — wipes every recorded meeting + the audio files
    on disk. Used by the 'Delete all meeting data' button in Settings."""
    _init_db()
    with _conn() as c:
        c.execute("DELETE FROM meetings")
    # Best-effort: rmtree the whole audio dir.
    try:
        import shutil
        import audio_meeting
        audio_dir = audio_meeting.audio_path_for(0).parent
        if audio_dir.exists():
            shutil.rmtree(audio_dir, ignore_errors=True)
    except Exception as e:
        log.warning(f"audio dir cleanup failed: {e}")
    return {"ok": True}


def update_user_notes(meeting_id: int, notes: str) -> dict:
    """Save the live notes the user types alongside the transcript."""
    _init_db()
    notes = (notes or "")[:50_000]
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE meetings SET user_notes = ?, updated_at = ? WHERE id = ?",
            (notes, now, int(meeting_id)),
        )
    return {"ok": True}


async def mark_recording_started(meeting_id: int) -> dict:
    """Start audio capture for `meeting_id`. Flips DB status to 'recording'
    and spawns the audio-tap sidecar + Deepgram socket."""
    import audio_meeting
    res = await audio_meeting.start_capture(meeting_id)
    if "error" in res:
        # Don't flip status if we couldn't actually start. The UI Stop
        # button still works (no-op) but the user can re-try.
        return res
    _set_status(meeting_id, "recording")
    return {"ok": True}


async def mark_recording_ended(meeting_id: int, transcript: str = "") -> dict:
    """Stop the audio tap and finalize the meeting. If a `transcript`
    argument is passed (e.g. from a manual-paste UI), it REPLACES the
    live-captured one — useful for testing without ScreenCaptureKit."""
    import audio_meeting
    if audio_meeting.active_meeting_id() == int(meeting_id):
        await audio_meeting.stop_capture()
    _init_db()
    now = int(time.time())
    with _conn() as c:
        if transcript:
            c.execute(
                "UPDATE meetings SET status = 'ended', transcript = ?, updated_at = ? "
                "WHERE id = ?",
                (transcript[:500_000], now, int(meeting_id)),
            )
        else:
            c.execute(
                "UPDATE meetings SET status = 'ended', updated_at = ? WHERE id = ?",
                (now, int(meeting_id)),
            )
    # If the user has opted in to share meetings with admin, kick off the
    # upload in the background so the response to the IPC handler doesn't
    # block on a 100 MB upload over slow Wi-Fi.
    try:
        asyncio.create_task(audio_meeting.upload_to_admin(int(meeting_id)))
    except Exception as e:
        log.warning(f"schedule admin upload failed: {e}")
    return {"ok": True}


def append_transcript_chunk(meeting_id: int, chunk: str) -> dict:
    """Append a finalized Deepgram chunk to the meeting's transcript.
    Called from the audio_meeting pump on every is_final result."""
    chunk = (chunk or "").strip()
    if not chunk:
        return {"id": int(meeting_id), "appended": False}
    _init_db()
    now = int(time.time())
    with _conn() as c:
        row = c.execute(
            "SELECT transcript FROM meetings WHERE id = ?", (int(meeting_id),)
        ).fetchone()
        if row is None:
            return {"id": int(meeting_id), "appended": False}
        existing = row["transcript"] or ""
        sep = " " if existing and not existing.endswith(("\n", " ")) else ""
        new_transcript = (existing + sep + chunk)[:500_000]
        c.execute(
            "UPDATE meetings SET transcript = ?, updated_at = ? WHERE id = ?",
            (new_transcript, now, int(meeting_id)),
        )
    return {"id": int(meeting_id), "appended": True, "transcript_len": len(new_transcript)}


def mark_skipped(meeting_id: int) -> dict:
    return _set_status(meeting_id, "skipped")


async def structure_meeting(meeting_id: int) -> dict:
    """Send the meeting's transcript + user notes to Railway /llm/structure-
    meeting. Saves the structured markdown back to the row. Returns the
    full updated meeting dict."""
    _init_db()
    m = get_meeting(meeting_id)
    if not m:
        return {"error": "meeting not found"}
    if not (m.get("transcript") or "").strip():
        return {"error": "no transcript to structure"}

    jwt = config.get_jwt()
    if not jwt:
        return {"error": "not signed in to uxie"}

    base = config.get_uxie_backend_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/llm/structure-meeting",
                headers={"Authorization": f"Bearer {jwt}"},
                json={
                    "title": m.get("title", ""),
                    "transcript": m.get("transcript", ""),
                    "user_notes": m.get("user_notes", ""),
                },
            )
        if resp.status_code == 429:
            return {"error": resp.json().get("detail", "rate limit hit")}
        resp.raise_for_status()
        structured = resp.json().get("structured", "")
    except httpx.HTTPError as e:
        log.warning(f"structure_meeting HTTP error: {e}")
        return {"error": str(e)}

    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE meetings SET structured_notes = ?, status = 'structured', "
            "updated_at = ? WHERE id = ?",
            (structured, now, int(meeting_id)),
        )
    return get_meeting(meeting_id) or {"error": "unknown"}


# ── Internals ─────────────────────────────────────────────────────────────────


def _set_status(meeting_id: int, status: str) -> dict:
    if status not in _STATUSES:
        return {"error": f"invalid status {status}"}
    _init_db()
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "UPDATE meetings SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, int(meeting_id)),
        )
    return {"ok": True}


def _row_to_dict(r: sqlite3.Row) -> dict:
    import json
    d = dict(r)
    try:
        d["attendees"] = json.loads(d.pop("attendees_json", "[]"))
    except Exception:
        d["attendees"] = []
    # Attach local WAV path if it exists. Frontend uses this to enable
    # the "Play audio" button.
    try:
        import audio_meeting
        p = audio_meeting.audio_path_for(d["id"])
        if p.exists() and p.stat().st_size > 44:  # 44 = empty WAV header
            d["audio_path"] = str(p)
            d["audio_size_bytes"] = p.stat().st_size
        else:
            d["audio_path"] = None
            d["audio_size_bytes"] = 0
    except Exception:
        d["audio_path"] = None
        d["audio_size_bytes"] = 0
    return d


def _upsert_event(ev: dict) -> tuple[int, bool]:
    """Insert or refresh metadata for `ev`. Returns (db_id, is_new)."""
    import json
    _init_db()
    now = int(time.time())
    event_id = ev["calendar_event_id"]
    with _conn() as c:
        existing = c.execute(
            "SELECT id, notified FROM meetings WHERE calendar_event_id = ?", (event_id,)
        ).fetchone()
        if existing:
            c.execute(
                """UPDATE meetings SET
                       title = ?, start_ts = ?, end_ts = ?, attendees_json = ?,
                       meeting_url = ?, organizer = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    ev["title"], ev["start_ts"], ev["end_ts"],
                    json.dumps(ev["attendees"]), ev["meeting_url"],
                    ev["organizer"], now, existing["id"],
                ),
            )
            return int(existing["id"]), False
        cur = c.execute(
            """INSERT INTO meetings
                   (calendar_event_id, title, start_ts, end_ts, attendees_json,
                    meeting_url, organizer, status, notified, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'detected', 0, ?, ?)""",
            (
                event_id, ev["title"], ev["start_ts"], ev["end_ts"],
                json.dumps(ev["attendees"]), ev["meeting_url"],
                ev["organizer"], now, now,
            ),
        )
        return int(cur.lastrowid), True


def _mark_notified(db_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE meetings SET notified = 1 WHERE id = ?", (db_id,))


# ── Calendar fetch ────────────────────────────────────────────────────────────


_CAL_BASE = "https://www.googleapis.com/calendar/v3"


async def _fetch_upcoming() -> list[dict]:
    """Hit Google Calendar's events.list for the next LOOKAHEAD_SECONDS.
    Returns parsed dicts ready for _upsert_event. Empty list on any failure
    so the poll loop never crashes."""
    token = oauth.get_token("google")
    if not token or not token.get("access_token"):
        return []

    now = datetime.now(timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(seconds=LOOKAHEAD_SECONDS)).isoformat().replace("+00:00", "Z")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_CAL_BASE}/calendars/primary/events",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": MAX_EVENTS_PER_POLL,
                },
            )
        if r.status_code == 401:
            log.warning("Calendar fetch 401 — token expired or scope missing")
            return []
        r.raise_for_status()
        items = r.json().get("items", [])
    except httpx.HTTPError as e:
        log.warning(f"calendar fetch failed: {e}")
        return []

    parsed: list[dict] = []
    for it in items:
        title = (it.get("summary") or "(No title)").strip()
        # Skip events the user RSVP'd "no" to — they're not attending so we
        # shouldn't be auto-prompting to record.
        self_attendee = next(
            (a for a in it.get("attendees", []) if a.get("self")), None
        )
        if self_attendee and self_attendee.get("responseStatus") == "declined":
            continue

        start = it.get("start", {})
        end = it.get("end", {})
        # Skip all-day events (no dateTime field) — those aren't meetings.
        if "dateTime" not in start:
            continue

        try:
            start_dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.get("dateTime", start["dateTime"]).replace("Z", "+00:00"))
        except Exception:
            continue

        meeting_url = it.get("hangoutLink") or _extract_url(it.get("description", "")) or _extract_url(it.get("location", ""))

        parsed.append({
            "calendar_event_id": it["id"],
            "title": title[:300],
            "start_ts": int(start_dt.timestamp()),
            "end_ts": int(end_dt.timestamp()),
            "attendees": [
                {
                    "email": (a.get("email") or "")[:200],
                    "name": (a.get("displayName") or "")[:200],
                    "response": a.get("responseStatus", ""),
                }
                for a in it.get("attendees", []) if a.get("email")
            ][:50],
            "meeting_url": (meeting_url or "")[:1000],
            "organizer": ((it.get("organizer") or {}).get("email") or "")[:200],
        })
    return parsed


_URL_REGEX = None


def _extract_url(text: str) -> str:
    """Pull the first Zoom/Meet/Teams URL out of free-form text."""
    import re
    global _URL_REGEX
    if _URL_REGEX is None:
        _URL_REGEX = re.compile(
            r"https?://[^\s<>\"']+(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com)[^\s<>\"']*",
            re.IGNORECASE,
        )
    if not text:
        return ""
    m = _URL_REGEX.search(text)
    return m.group(0) if m else ""


# ── Poll loop ─────────────────────────────────────────────────────────────────


_event_emitter: Callable[[str, Any], Awaitable[None]] | None = None


def set_event_emitter(fn: Callable[[str, Any], Awaitable[None]]) -> None:
    """main.py installs ConnectionManager.broadcast here so we can push
    `meeting:detected` to renderers."""
    global _event_emitter
    _event_emitter = fn


async def _emit(event: str, payload: Any) -> None:
    if _event_emitter is None:
        return
    try:
        await _event_emitter(event, payload)
    except Exception as e:
        log.warning(f"meetings._emit({event}) failed: {e}")


async def _poll_once() -> None:
    events = await _fetch_upcoming()
    if not events:
        return
    now = time.time()
    for ev in events:
        db_id, is_new = _upsert_event(ev)
        # Ready-to-notify = within LEAD_IN_SECONDS of start, not past end,
        # and we haven't notified before.
        seconds_until_start = ev["start_ts"] - now
        if not (-30 <= seconds_until_start <= LEAD_IN_SECONDS):
            continue
        with _conn() as c:
            r = c.execute(
                "SELECT notified, status FROM meetings WHERE id = ?", (db_id,)
            ).fetchone()
        if not r or r["notified"]:
            continue
        if r["status"] != "detected":
            continue
        _mark_notified(db_id)
        full = get_meeting(db_id) or {}
        await _emit("meeting:detected", full)


async def start_poll_loop() -> None:
    """Background task — never raises. Cancellable via the lifespan."""
    _init_db()
    log.info(f"meetings poll loop starting (interval={POLL_INTERVAL_SECONDS}s)")
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"poll iteration crashed: {e}")
        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
