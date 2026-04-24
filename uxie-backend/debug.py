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
