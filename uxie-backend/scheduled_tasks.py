"""Scheduled / recurring tasks (v1.2).

User-configured workflows that fire at a chosen local time. The first
template is **Morning Brief** — runs at e.g. 8am every day, parallel-fans
out to Gmail / Calendar / Drive workers, synthesizes a Markdown brief,
delivers via macOS notification + email.

Architecture:
    ScheduledTask  ── kind=morning_brief, run_time_local="08:00", tz="Asia/Kolkata"
        ▼
    cron_worker (runs every 60s on Railway lifespan)
        if now_local(tz) ≥ run_time AND last_fired_at < today → fire
        ▼
    spawn one BackgroundTask + run the template-specific generator
        ▼
    write transcript to BackgroundTask.result_md AND email it via Resend

Endpoints:
    GET    /scheduled_tasks                 list caller's
    POST   /scheduled_tasks                 create
    PATCH  /scheduled_tasks/{id}            partial update (run_time, tz, enabled, delivery)
    DELETE /scheduled_tasks/{id}            delete

The cron worker is launched from main.py's lifespan as `asyncio.create_task`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone as _tz
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import SessionLocal, User, get_db
from db_ios import BackgroundTask, ScheduledTask, TaskEvent
from proxy import _llm_base_and_key, get_http
from settings import get_settings

try:
    import connectors as _connectors
except Exception:
    _connectors = None  # type: ignore[assignment]

_log = logging.getLogger("scheduled_tasks")
_settings = get_settings()


# ── IDs ───────────────────────────────────────────────────────────────────────


def _ulid() -> str:
    return f"{int(time.time() * 1000):013d}_{secrets.token_hex(6)}"


# ── Timezone helpers ──────────────────────────────────────────────────────────


def _now_in_tz(tzname: str) -> datetime:
    """Best-effort local-time conversion. Falls back to UTC if zoneinfo
    can't resolve the name (e.g. odd inputs from older clients)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tzname))
    except Exception:
        return datetime.now(_tz.utc)


def _is_due(st: ScheduledTask, now: datetime) -> bool:
    """True if it's >= run_time today in the user's local TZ AND we
    haven't already fired today. The 60s polling cadence means a brief
    set to 08:00 actually fires somewhere in [08:00, 08:01) — close enough."""
    if not st.enabled:
        return False
    try:
        hh, mm = st.run_time_local.split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except Exception:
        return False
    if now < target:
        return False
    # Already fired today?
    if st.last_fired_at is not None:
        last = st.last_fired_at
        # last_fired_at is UTC; compare its date in the user's local tz
        try:
            from zoneinfo import ZoneInfo
            last_local = last.astimezone(ZoneInfo(st.timezone))
        except Exception:
            last_local = last
        if last_local.date() == now.date():
            return False
    return True


# ── Morning Brief generator ───────────────────────────────────────────────────


_MORNING_BRIEF_SYSTEM_PROMPT = """You are Uxie's Morning Brief writer. You've been handed the results of
parallel fact-finding agents: today's calendar, unread Gmail, and any
notable Drive activity. Synthesize them into a tight Markdown brief the
user can read in 60 seconds while making coffee.

Required structure (omit a section entirely if there's nothing for it):

## Today's schedule
- HH:MM  Meeting title  (attendees: alice@…, bob@…)
…
(call out conflicts, long blocks, travel/buffer time)

## Inbox highlights
Group by urgency. Lead with anything the user needs to reply to today.
For each: who it's from, one-line summary, why it matters.

## Heads-up
Anything else worth flagging — Drive doc with recent comments, an event
that needs prep, a deadline approaching, etc.

Style:
- Terse. The user is reading on their phone.
- No filler ("here is your brief"), no closing line.
- Action-oriented bullets ("Reply to Sarah re. pricing" not "Sarah emailed about pricing")
- If a section is empty, just leave it out. Don't write "no urgent emails".
- End with one sentence energy: a single observation, not a generic "have a great day".
"""


async def _morning_brief_generate(db: AsyncSession, user: User) -> str:
    """Run the actual brief generation: fan out to Gmail + Calendar in
    parallel, hand the results to GPT-4o, return the markdown."""
    if _connectors is None:
        return "*(connectors not loaded — brief unavailable)*"

    # Parallel fact-finding — each returns a (label, str) tuple.
    async def _calendar_today() -> tuple[str, str]:
        try:
            ok, res = await _connectors.execute(
                db, user.id, "calendar_list_events", {"days_ahead": 1}
            )
            return ("calendar", res if isinstance(res, str) else json.dumps(res, default=str))
        except Exception as e:
            return ("calendar", f"(calendar fetch failed: {e})")

    async def _gmail_recent() -> tuple[str, str]:
        try:
            ok, res = await _connectors.execute(
                db, user.id, "gmail_search",
                {"query": "is:unread newer_than:1d", "limit": 10},
            )
            return ("gmail", res if isinstance(res, str) else json.dumps(res, default=str))
        except Exception as e:
            return ("gmail", f"(gmail fetch failed: {e})")

    results = await asyncio.gather(_calendar_today(), _gmail_recent(), return_exceptions=False)
    sections = {label: text for label, text in results}

    user_msg = (
        f"# Raw inputs for Morning Brief — {datetime.now(_tz.utc).strftime('%A %B %-d')}\n\n"
        f"## Calendar (next 24h, primary calendar)\n{sections.get('calendar', '(none)')}\n\n"
        f"## Unread Gmail (last 24h)\n{sections.get('gmail', '(none)')}\n"
    )

    base_url, api_key = _llm_base_and_key("openai")
    http = get_http()
    resp = await http.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o",
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": _MORNING_BRIEF_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        },
        timeout=90,
    )
    if resp.status_code != 200:
        return f"*(Morning Brief LLM call failed: {resp.status_code} {resp.text[:200]})*"
    data = resp.json()
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


# ── Email delivery (Resend) ───────────────────────────────────────────────────


async def _send_email(to: str, subject: str, markdown: str) -> bool:
    """Ship the brief via Resend. Renders the markdown into <pre>-wrapped
    HTML — keeps formatting readable in Gmail without needing a markdown
    renderer dep."""
    key = (_settings.resend_api_key or "").strip()
    if not key:
        _log.warning("resend_api_key not set — skipping email delivery")
        return False
    sender = _settings.resend_from or "Uxie <noreply@uxie.ai>"
    # Minimal HTML wrapper. Markdown rendered as text — Gmail will
    # respect linebreaks and headings still read fine prefixed with #.
    html = (
        "<div style='font-family: -apple-system, BlinkMacSystemFont, sans-serif; "
        "max-width: 640px; padding: 16px;'>"
        "<pre style='white-space: pre-wrap; font-family: inherit; font-size: 14px; "
        "line-height: 1.5;'>"
        + markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre>"
        "<hr style='margin-top: 24px; border: none; border-top: 1px solid #eee;'/>"
        "<p style='font-size: 11px; color: #999; margin-top: 16px;'>"
        "Sent by Uxie — turn off in Settings → Briefings"
        "</p>"
        "</div>"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"from": sender, "to": [to], "subject": subject, "html": html},
            )
        if r.status_code >= 300:
            _log.warning("resend send failed (%d): %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        _log.warning("resend exception: %s", e)
        return False


# ── Firing a scheduled task ───────────────────────────────────────────────────


async def _fire(st_id: str) -> None:
    """Create a BackgroundTask + execute the kind-specific generator + email."""
    async with SessionLocal() as db:
        st = (await db.execute(select(ScheduledTask).where(ScheduledTask.id == st_id))).scalar_one_or_none()
        if st is None or not st.enabled:
            return
        user = (await db.execute(select(User).where(User.id == st.user_id))).scalar_one_or_none()
        if user is None:
            return

        # 1. Spawn a BackgroundTask shell so the user can see "this fired" in
        #    the Tasks tab with the brief markdown in result_md.
        task_id = _ulid()
        db.add(BackgroundTask(
            id=task_id, user_id=user.id,
            prompt=f"[Scheduled: {st.kind}] {st.run_time_local} {st.timezone}",
            status="running",
        ))
        st.last_task_id = task_id
        st.last_fired_at = datetime.now(_tz.utc)
        st.updated_at = datetime.now(_tz.utc)
        await db.commit()

        # 2. Run the kind-specific generator.
        try:
            if st.kind == "morning_brief":
                brief = await _morning_brief_generate(db, user)
            else:
                brief = f"*(unknown scheduled task kind: {st.kind})*"
        except Exception as e:
            _log.exception("scheduled task %s generator failed", st_id)
            brief = f"*(generator error: {e})*"

        # 3. Persist the result back to the BackgroundTask row.
        bt = (await db.execute(
            select(BackgroundTask).where(BackgroundTask.id == task_id)
        )).scalar_one_or_none()
        if bt is not None:
            bt.status = "completed"
            bt.result_md = brief
            bt.completed_at = datetime.now(_tz.utc)
            bt.updated_at = datetime.now(_tz.utc)
        db.add(TaskEvent(
            task_id=task_id, seq=0, kind="final_text", data={"text": brief},
        ))
        await db.commit()

        # 4. Email if configured.
        delivery = st.delivery_json or {}
        if delivery.get("email", True):
            subject = "Your Uxie Morning Brief — " + datetime.now(_tz.utc).strftime("%A %B %-d")
            await _send_email(user.email, subject, brief)


# ── Cron worker ───────────────────────────────────────────────────────────────


async def cron_worker() -> None:
    """Polls every 60s. For each ScheduledTask whose run_time has passed
    in its user's tz today AND hasn't fired today, kick off `_fire`."""
    _log.info("scheduled_tasks cron worker starting (60s poll)")
    while True:
        try:
            async with SessionLocal() as db:
                rows = (await db.execute(
                    select(ScheduledTask).where(ScheduledTask.enabled == True)  # noqa: E712
                )).scalars().all()
                due_ids: list[str] = []
                for st in rows:
                    now = _now_in_tz(st.timezone)
                    if _is_due(st, now):
                        due_ids.append(st.id)
            for st_id in due_ids:
                # Each fire opens its own DB session — keeps the cron
                # session short.
                asyncio.create_task(_fire(st_id))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.warning("cron iteration crashed: %s", e)
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise


# ── HTTP endpoints ────────────────────────────────────────────────────────────


class ScheduledTaskCreate(BaseModel):
    kind: str = Field(..., max_length=64)
    run_time_local: str = Field(..., min_length=4, max_length=5)
    timezone: str = Field(..., max_length=64)
    enabled: bool = True
    delivery: dict | None = None
    config: dict | None = None


class ScheduledTaskPatch(BaseModel):
    run_time_local: str | None = Field(None, min_length=4, max_length=5)
    timezone: str | None = Field(None, max_length=64)
    enabled: bool | None = None
    delivery: dict | None = None
    config: dict | None = None


def _row_to_dict(st: ScheduledTask) -> dict:
    return {
        "id": st.id,
        "kind": st.kind,
        "enabled": st.enabled,
        "run_time_local": st.run_time_local,
        "timezone": st.timezone,
        "delivery": st.delivery_json or {},
        "config": st.config_json or {},
        "last_fired_at": st.last_fired_at.isoformat() if st.last_fired_at else None,
        "last_task_id": st.last_task_id,
        "created_at": st.created_at.isoformat() if st.created_at else None,
    }


async def scheduled_list(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    rows = (await db.execute(
        select(ScheduledTask).where(ScheduledTask.user_id == user.id)
        .order_by(desc(ScheduledTask.created_at))
    )).scalars().all()
    return {"scheduled_tasks": [_row_to_dict(r) for r in rows]}


async def scheduled_create(
    body: ScheduledTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    if body.kind not in {"morning_brief"}:
        raise HTTPException(400, f"unsupported kind: {body.kind}")
    # Validate run_time_local "HH:MM" shape.
    try:
        hh, mm = body.run_time_local.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError("out of range")
    except Exception:
        raise HTTPException(400, "run_time_local must be HH:MM in 24h format")

    st_id = _ulid()
    db.add(ScheduledTask(
        id=st_id, user_id=user.id, kind=body.kind,
        enabled=body.enabled,
        run_time_local=body.run_time_local,
        timezone=body.timezone,
        delivery_json=body.delivery or {"notification": True, "email": True},
        config_json=body.config or {},
    ))
    await db.commit()
    st = (await db.execute(select(ScheduledTask).where(ScheduledTask.id == st_id))).scalar_one()
    return _row_to_dict(st)


async def scheduled_patch(
    st_id: str,
    body: ScheduledTaskPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    st = (await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == st_id, ScheduledTask.user_id == user.id,
        )
    )).scalar_one_or_none()
    if st is None:
        raise HTTPException(404, "scheduled task not found")
    if body.run_time_local is not None:
        st.run_time_local = body.run_time_local
    if body.timezone is not None:
        st.timezone = body.timezone
    if body.enabled is not None:
        st.enabled = body.enabled
    if body.delivery is not None:
        st.delivery_json = body.delivery
    if body.config is not None:
        st.config_json = body.config
    st.updated_at = datetime.now(_tz.utc)
    await db.commit()
    return _row_to_dict(st)


async def scheduled_delete(
    st_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    st = (await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == st_id, ScheduledTask.user_id == user.id,
        )
    )).scalar_one_or_none()
    if st is None:
        return {"ok": True, "already_deleted": True}
    await db.delete(st)
    await db.commit()
    return {"ok": True}
