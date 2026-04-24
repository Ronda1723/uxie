"""
Internal admin dashboard.

Endpoints:
  GET /admin/dashboard    — HTML page (loads stats.json via fetch)
  GET /admin/stats.json   — aggregated stats for the UI
  GET /admin/users.json   — full per-user table
  GET /admin/user/{id}.json — drill-down for one user

Auth: the caller's JWT is resolved to a User via current_user; that user's
email must be in settings.admin_emails. Non-admins get 403.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import r2
from auth import current_user
from db import LLMUsage, SessionLog, STTUsage, Usage, User, get_db
from settings import get_settings

_settings = get_settings()
_DASHBOARD_HTML = Path(__file__).parent / "admin_dashboard.html"


async def _require_admin(user: User = Depends(current_user)) -> User:
    allowed = _settings.admin_email_set()
    if not allowed:
        raise HTTPException(503, "Admin dashboard not configured (set ADMIN_EMAILS)")
    if (user.email or "").lower() not in allowed:
        raise HTTPException(403, "Not an admin")
    return user


async def dashboard_html() -> HTMLResponse:
    """Public HTML shell — all data endpoints below require admin JWT. The
    page reads ?token=<jwt> from its URL and stores it in sessionStorage,
    then every subsequent fetch carries Authorization: Bearer <token>."""
    try:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(500, "admin_dashboard.html missing from backend deploy")


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def stats_json(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> JSONResponse:
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)
    month_start = _month_start_utc()

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()

    # Active users = distinct user_ids with any LLM OR STT event in the window
    async def _active_since(ts: datetime) -> int:
        q1 = select(LLMUsage.user_id).where(LLMUsage.created_at >= ts).distinct()
        q2 = select(STTUsage.user_id).where(STTUsage.created_at >= ts).distinct()
        ids: set[int] = set()
        for row in (await db.execute(q1)).all():
            ids.add(row[0])
        for row in (await db.execute(q2)).all():
            ids.add(row[0])
        return len(ids)

    dau = await _active_since(since_24h)
    wau = await _active_since(since_7d)
    mau = await _active_since(month_start)

    new_users_24h = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= since_24h)
    )).scalar_one()
    new_users_mtd = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= month_start)
    )).scalar_one()

    # Cost + volume totals, grouped by (provider, model) for LLM
    async def _llm_totals(ts: datetime):
        q = select(
            LLMUsage.provider,
            LLMUsage.model,
            func.count(LLMUsage.id),
            func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
            func.coalesce(func.sum(LLMUsage.cost_usd_est), 0.0),
        ).where(LLMUsage.created_at >= ts).group_by(LLMUsage.provider, LLMUsage.model)
        rows = (await db.execute(q)).all()
        return [
            {
                "provider": r[0], "model": r[1], "calls": int(r[2]),
                "prompt_tokens": int(r[3]), "completion_tokens": int(r[4]),
                "cost_usd_est": float(r[5]),
            }
            for r in rows
        ]

    async def _stt_totals(ts: datetime):
        r = (await db.execute(
            select(
                func.count(STTUsage.id),
                func.coalesce(func.sum(STTUsage.cost_usd_est), 0.0),
            ).where(STTUsage.created_at >= ts)
        )).one()
        return {"sessions": int(r[0]), "cost_usd_est": float(r[1])}

    llm_24h = await _llm_totals(since_24h)
    llm_mtd = await _llm_totals(month_start)
    stt_24h = await _stt_totals(since_24h)
    stt_mtd = await _stt_totals(month_start)

    llm_cost_24h = sum(x["cost_usd_est"] for x in llm_24h)
    llm_cost_mtd = sum(x["cost_usd_est"] for x in llm_mtd)

    return JSONResponse({
        "generated_at": now.isoformat(),
        "users": {
            "total": int(total_users),
            "new_24h": int(new_users_24h),
            "new_mtd": int(new_users_mtd),
            "dau": dau,
            "wau": wau,
            "mau": mau,
        },
        "llm": {"last_24h": llm_24h, "mtd": llm_mtd},
        "stt": {"last_24h": stt_24h, "mtd": stt_mtd},
        "totals": {
            # Split by provider kind so the dashboard can show three separate
            # cost cards per timeframe.
            "cost_usd_llm_24h": round(llm_cost_24h, 4),
            "cost_usd_stt_24h": round(stt_24h["cost_usd_est"], 4),
            "cost_usd_combined_24h": round(llm_cost_24h + stt_24h["cost_usd_est"], 4),
            "cost_usd_llm_mtd": round(llm_cost_mtd, 4),
            "cost_usd_stt_mtd": round(stt_mtd["cost_usd_est"], 4),
            "cost_usd_combined_mtd": round(llm_cost_mtd + stt_mtd["cost_usd_est"], 4),
        },
    })


async def users_json(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> JSONResponse:
    month_start = _month_start_utc()

    # Pull users
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()

    # LLM aggregates per user (MTD)
    llm_q = select(
        LLMUsage.user_id,
        func.count(LLMUsage.id),
        func.coalesce(func.sum(LLMUsage.cost_usd_est), 0.0),
        func.max(LLMUsage.created_at),
    ).where(LLMUsage.created_at >= month_start).group_by(LLMUsage.user_id)
    llm_rows = {r[0]: (int(r[1]), float(r[2]), r[3]) for r in (await db.execute(llm_q)).all()}

    # STT aggregates per user (MTD)
    stt_q = select(
        STTUsage.user_id,
        func.count(STTUsage.id),
        func.coalesce(func.sum(STTUsage.cost_usd_est), 0.0),
        func.max(STTUsage.created_at),
    ).where(STTUsage.created_at >= month_start).group_by(STTUsage.user_id)
    stt_rows = {r[0]: (int(r[1]), float(r[2]), r[3]) for r in (await db.execute(stt_q)).all()}

    # Current-month usage row (rate-limiter's counters) for dictation/command counts
    month_tag = datetime.now(timezone.utc).strftime("%Y-%m")
    usage_q = select(Usage).where(Usage.month == month_tag)
    usage_rows = {u.user_id: u for u in (await db.execute(usage_q)).scalars().all()}

    out = []
    for u in users:
        llm_calls, llm_cost, llm_last = llm_rows.get(u.id, (0, 0.0, None))
        stt_sessions, stt_cost, stt_last = stt_rows.get(u.id, (0, 0.0, None))
        usage_row = usage_rows.get(u.id)
        last_seen = max([t for t in (llm_last, stt_last) if t is not None], default=None)
        out.append({
            "id": u.id,
            "email": u.email,
            "tier": u.tier,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "referral_code": u.referral_code,
            "free_days_remaining": u.free_days_remaining,
            "dictation_count_mtd": usage_row.dictation_count if usage_row else 0,
            "command_count_mtd": usage_row.command_count if usage_row else 0,
            "llm_calls_mtd": llm_calls,
            "stt_sessions_mtd": stt_sessions,
            "cost_usd_mtd": round(llm_cost + stt_cost, 4),
        })
    return JSONResponse({"users": out})


async def sessions_json(
    limit: int = 50,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> JSONResponse:
    """Recent session transcripts across all users (or one, via ?user_id=)."""
    q = select(SessionLog, User.email).join(User, User.id == SessionLog.user_id)
    if user_id:
        q = q.where(SessionLog.user_id == user_id)
    q = q.order_by(SessionLog.created_at.desc()).limit(min(limit, 200))
    rows = (await db.execute(q)).all()
    return JSONResponse({
        "sessions": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "email": email,
                "session_id": s.session_id,
                "action": s.action,
                "provider": s.provider,
                "model": s.model,
                "input_text": s.input_text,
                "output_text": s.output_text,
                "audio_r2_key": s.audio_r2_key,
                "duration_ms": s.duration_ms,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for (s, email) in rows
        ]
    })


async def audio_redirect(
    session_row_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
):
    """Admin hits /admin/audio/{session_row_id}; we look up the R2 key and
    redirect to a 1h-TTL presigned URL so the browser's <audio> tag streams
    directly from R2 without proxying bytes through Railway."""
    row = (await db.execute(
        select(SessionLog).where(SessionLog.id == session_row_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "session not found")
    if not row.audio_r2_key:
        raise HTTPException(404, "no audio recorded for this session")
    url = r2.presigned_get_url(row.audio_r2_key, expires_in_seconds=3600)
    if not url:
        raise HTTPException(503, "R2 not configured or presign failed")
    return RedirectResponse(url, status_code=302)


async def user_detail_json(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_admin),
) -> JSONResponse:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")

    recent_llm = (await db.execute(
        select(LLMUsage).where(LLMUsage.user_id == user_id)
        .order_by(LLMUsage.created_at.desc()).limit(50)
    )).scalars().all()

    recent_stt = (await db.execute(
        select(STTUsage).where(STTUsage.user_id == user_id)
        .order_by(STTUsage.created_at.desc()).limit(50)
    )).scalars().all()

    return JSONResponse({
        "user": {
            "id": u.id, "email": u.email, "tier": u.tier,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "referral_code": u.referral_code,
            "free_days_remaining": u.free_days_remaining,
        },
        "recent_llm": [
            {
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "provider": r.provider, "model": r.model, "action": r.action,
                "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                "cost_usd_est": round(float(r.cost_usd_est), 6),
                "duration_ms": r.duration_ms,
            }
            for r in recent_llm
        ],
        "recent_stt": [
            {
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "provider": r.provider,
                "deepgram_key_id": r.deepgram_key_id,
                "cost_usd_est": round(float(r.cost_usd_est), 6),
            }
            for r in recent_stt
        ],
    })
