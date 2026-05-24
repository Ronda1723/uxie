"""
Admin-only debug endpoints.

  POST /debug/upload-audio — client uploads raw int16 mono PCM bytes for the
                             just-finished dictation/command session. The blob
                             is wrapped as WAV and stored in R2, and the
                             corresponding session_log row is stamped with the
                             object key.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import r2
from auth import current_user
from db import SessionLog, User, get_db

_log = logging.getLogger("debug")


async def upload_audio(
    request: Request,
    x_session_id: str = Header(...),
    x_sample_rate: int = Header(16000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    if not r2.configured():
        raise HTTPException(503, "R2 audio storage is not configured (missing env vars).")

    # Client sends raw int16 PCM bytes as the request body.
    pcm = await request.body()
    if not pcm:
        raise HTTPException(400, "Empty audio body.")
    if len(pcm) > 50 * 1024 * 1024:  # 50 MB safety cap (~26 min of 16kHz mono)
        raise HTTPException(413, "Audio too large.")

    # Wrap PCM as WAV so the browser <audio> can play it directly.
    wav = r2.pcm_to_wav(pcm, sample_rate=x_sample_rate)
    key = r2.build_audio_key(user.id, x_session_id)

    ok = await r2.put_bytes_async(key, wav, content_type="audio/wav")
    if not ok:
        raise HTTPException(502, "R2 upload failed — check server logs.")

    # Attach the object key to the matching session_log row, if one exists.
    # We match by (user_id, session_id) which is what the client passed to the
    # LLM call. If the session_log row hasn't been written yet (race: /llm
    # still streaming), we still succeeded on R2 — the admin dashboard
    # cross-references session_id → key at read time as a fallback.
    try:
        row = (await db.execute(
            select(SessionLog)
            .where(SessionLog.user_id == user.id, SessionLog.session_id == x_session_id)
            .order_by(SessionLog.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if row is not None:
            row.audio_r2_key = key
            await db.commit()
    except Exception as e:
        _log.warning("attach audio_r2_key failed: %s", e)

    return {"ok": True, "key": key, "bytes": len(wav), "pcm_bytes": len(pcm)}


# ── Meeting upload ────────────────────────────────────────────────────────────


from fastapi import File, Form, UploadFile  # noqa: E402

from db_ios import MeetingRecording  # noqa: E402


async def upload_meeting(
    title: str = Form(...),
    local_meeting_id: int = Form(...),
    duration_seconds: int = Form(0),
    transcript_preview: str = Form(""),
    structured_notes: str = Form(""),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Receive a meeting's WAV file + minimal metadata + transcript
    preview from the client. Audio bytes go to R2; row goes to
    meeting_recordings so /admin/meetings.json can list them.

    Strictly opt-in on the client (controlled by the
    `share_meetings_with_admin` setting). Full transcripts stay local —
    we only get the first ~2000 chars for the admin to grep over."""
    if not r2.configured():
        raise HTTPException(503, "R2 audio storage is not configured.")

    wav_bytes = await audio.read()
    if not wav_bytes:
        raise HTTPException(400, "Empty audio.")
    # 200 MB cap — 200 MB ≈ ~30 min of stereo 48 kHz, plenty of slack
    # for a 16 kHz mono mix of an hour-long meeting (~115 MB).
    if len(wav_bytes) > 200 * 1024 * 1024:
        raise HTTPException(413, "Audio too large.")

    key = f"meetings/{user.id}/{local_meeting_id}.wav"
    ok = await r2.put_bytes_async(key, wav_bytes, content_type="audio/wav")
    if not ok:
        raise HTTPException(502, "R2 upload failed.")

    # Upsert a MeetingRecording row keyed by (user_id, local_meeting_id)
    # so re-uploads (e.g. user re-structured the same meeting) replace
    # rather than duplicate.
    existing = (await db.execute(
        select(MeetingRecording).where(
            MeetingRecording.user_id == user.id,
            MeetingRecording.local_meeting_id == local_meeting_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.title = title[:300]
        existing.duration_seconds = int(duration_seconds)
        existing.audio_r2_key = key
        existing.transcript_preview = (transcript_preview or "")[:2000]
        existing.structured_notes = (structured_notes or "")[:8000]
    else:
        db.add(MeetingRecording(
            user_id=user.id,
            local_meeting_id=int(local_meeting_id),
            title=title[:300],
            duration_seconds=int(duration_seconds),
            audio_r2_key=key,
            transcript_preview=(transcript_preview or "")[:2000],
            structured_notes=(structured_notes or "")[:8000],
        ))
    await db.commit()
    return {"ok": True, "key": key, "bytes": len(wav_bytes)}
