"""Background-task API.

Lets a client describe a long-running task ("summarize my unread Gmail and
draft a reply to the urgent ones") and walk away. The agent loop runs
detached from the HTTP request — once /tasks/create returns, the task
keeps executing on Railway even if the client disconnects, the Mac sleeps,
or the user quits Uxie. Client polls /tasks/{id} for progress.

Endpoints:
    POST  /tasks/create       — create a task, returns its id immediately
    GET   /tasks              — list the caller's recent tasks
    GET   /tasks/{id}         — current state + ordered event log
    POST  /tasks/{id}/cancel  — request cancellation (best-effort)

Design choices for v1.1.0:
    - Polling, not SSE. Client polls /tasks/{id} every 2s while running.
      SSE is on the roadmap (v1.2) but polling is simpler to ship and
      survives connection drops gracefully.
    - Read-only tools only. Sending email, creating events, posting to
      Slack, etc. are gated behind an approval flow we'll wire in v1.2.
      v1.1.0 ships safe tools: gmail_search/gmail_read, calendar_list_events,
      drive_search/drive_read.
    - Per-user burst limit (10/hour, 30/day) on top of the monthly
      `command` quota. Background tasks consume Groq/OpenAI tokens fast
      so we double-protect against a stolen JWT.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import SessionLocal, User, get_db
from db_ios import BackgroundTask, TaskEvent
from limits import check_and_increment, check_burst
from proxy import _llm_base_and_key, get_http
from settings import get_settings

try:
    import connectors as _connectors
except Exception:  # noqa: BLE001
    _connectors = None  # type: ignore[assignment]

_log = logging.getLogger("tasks")
_settings = get_settings()

# Hard cap on agent turns. Each turn = one LLM call. 8 is generous — most
# multi-step tasks finish in 3-5 turns. Without this, an LLM stuck in a
# tool-call loop could burn unbounded tokens.
MAX_TASK_TURNS = 8

# Read-only tools the LLM can call freely — no approval required.
READ_ONLY_TOOLS: set[str] = {
    "gmail_search", "gmail_read",
    "calendar_list_events", "calendar_check_availability",
    "drive_search", "drive_read", "drive_list",
    "slack_search", "slack_list_channels", "slack_read_channel",
}

# Destructive tools — the LLM CAN call these in background tasks, but
# we park execution until the user clicks Approve in the Tasks tab.
# Each gets a 5-minute approval window before auto-cancelling.
DESTRUCTIVE_TOOLS: set[str] = {
    "gmail_send", "gmail_reply", "gmail_draft",
    "slack_send_message",
    "calendar_create_event",
}

# Union — what the agent loop will accept.
ALL_ALLOWED_TOOLS: set[str] = READ_ONLY_TOOLS | DESTRUCTIVE_TOOLS

# Approval window for a parked destructive tool call before auto-cancel.
APPROVAL_TIMEOUT_S = 300

DEFAULT_MODEL = "gpt-4o"
DEFAULT_PROVIDER = "openai"

# Per-user burst limit for /tasks/create. Belt-and-braces on top of the
# monthly command counter.
BURST_PER_HOUR = 10
BURST_PER_DAY = 30


# ── ULID-ish id ───────────────────────────────────────────────────────────────


def _ulid() -> str:
    """Lexicographically-sortable id (millisecond timestamp + random suffix)."""
    millis = int(time.time() * 1000)
    return f"{millis:013d}_{secrets.token_hex(6)}"


# ── Event persistence ────────────────────────────────────────────────────────


async def _append_event(
    db: AsyncSession, task_id: str, kind: str, data: dict | None = None
) -> None:
    """Append one row to task_events. Caller commits."""
    # seq is one greater than the current max for this task.
    last = (await db.execute(
        select(TaskEvent.seq).where(TaskEvent.task_id == task_id)
        .order_by(desc(TaskEvent.seq)).limit(1)
    )).scalar_one_or_none()
    next_seq = (last or 0) + 1 if last is not None else 0
    db.add(TaskEvent(task_id=task_id, seq=next_seq, kind=kind, data=data or {}))


async def _update_task_status(
    db: AsyncSession,
    task_id: str,
    *,
    status: str | None = None,
    result_md: str | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    """Patch the BackgroundTask row. Caller commits."""
    task = (await db.execute(
        select(BackgroundTask).where(BackgroundTask.id == task_id)
    )).scalar_one_or_none()
    if task is None:
        return
    if status is not None:
        task.status = status
    if result_md is not None:
        task.result_md = result_md
    if error is not None:
        task.error = error
    task.updated_at = datetime.now(timezone.utc)
    if completed:
        task.completed_at = datetime.now(timezone.utc)


# ── Tool schema filtering ─────────────────────────────────────────────────────


async def _allowed_tool_schemas(db: AsyncSession, user_id: int) -> list[dict]:
    """Tools the agent can see: read-only + destructive (gated). The
    destructive ones park on approval before actually executing."""
    if _connectors is None:
        return []
    try:
        all_schemas = await _connectors.tool_schemas_for_user(db, user_id)
    except Exception:
        _log.warning("connector schema lookup failed", exc_info=True)
        return []
    return [s for s in all_schemas if s.get("function", {}).get("name") in ALL_ALLOWED_TOOLS]


# ── Approval gate ────────────────────────────────────────────────────────────
# Each destructive tool call parks on an asyncio.Event keyed by
# (task_id, tool_call_id). /tasks/{id}/approve resolves it.

from dataclasses import dataclass, field


@dataclass
class _ApprovalGate:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    edited_args: dict | None = None


_APPROVAL_GATES: dict[tuple[str, str], _ApprovalGate] = {}
_APPROVAL_LOCK = asyncio.Lock()


async def _park_for_approval(
    task_id: str, tool_call_id: str, timeout_s: float
) -> tuple[bool, dict | None]:
    """Block until /tasks/{id}/approve fires for this tool_call. Returns
    (approved, edited_args_or_None). Times out → (False, None)."""
    gate = _ApprovalGate()
    async with _APPROVAL_LOCK:
        _APPROVAL_GATES[(task_id, tool_call_id)] = gate
    try:
        await asyncio.wait_for(gate.event.wait(), timeout=timeout_s)
        return gate.approved, gate.edited_args
    except asyncio.TimeoutError:
        return False, None
    finally:
        async with _APPROVAL_LOCK:
            _APPROVAL_GATES.pop((task_id, tool_call_id), None)


async def _resolve_approval(
    task_id: str, tool_call_id: str, approved: bool, edited_args: dict | None,
) -> bool:
    async with _APPROVAL_LOCK:
        gate = _APPROVAL_GATES.get((task_id, tool_call_id))
    if gate is None:
        return False
    gate.approved = approved
    gate.edited_args = edited_args
    gate.event.set()
    return True


# ── Agent loop ────────────────────────────────────────────────────────────────


SYSTEM_PROMPT_TEMPLATE = """You are Uxie's background-task agent. The user has given you a task to
run in the background while they keep working.

AVAILABLE TOOLS (you MUST use these — do not say "I can't access X" if
a tool for X is in this list):
{tool_list}

Hard rules:
1. ALWAYS call the relevant tool when the user's request maps to one of
   the available tools. NEVER respond with "I can't check your calendar"
   or "you'll need to look that up" when a tool for that exact thing is
   listed above. Use the tool.
2. Plan briefly, then act. Don't narrate every step.
3. Don't ask the user clarifying questions — they're not around to answer.
   Make a reasonable assumption and proceed.
4. Be thorough. Multiple tool calls are encouraged — search first, read
   the relevant results, then summarize.
5. End with a clear Markdown summary of what you found. Use headings,
   bullets, and action items where it helps the user scan.
6. If a tool returns "user has not connected X" or a permission error,
   tell the user to open Settings → Connectors and reconnect that
   provider — don't try to guess the answer without the tool.
7. You have a hard cap of 8 turns. Prioritize getting useful information
   into the summary over thoroughness.

You cannot send messages, create events, or do anything destructive in
this mode — only the read-only tools above are available.
"""


def _build_system_prompt(tool_schemas: list[dict]) -> str:
    """Render SYSTEM_PROMPT_TEMPLATE with the actual list of tools the LLM
    has access to. Listing them inline (not just via the OpenAI tools=…
    field) measurably improves tool-call rates."""
    if not tool_schemas:
        tool_list = "(no tools are currently available — the user has not connected any data providers)"
    else:
        lines = []
        for s in tool_schemas:
            fn = s.get("function") or {}
            name = fn.get("name", "?")
            desc = (fn.get("description") or "").strip().split("\n")[0][:120]
            lines.append(f"  • {name} — {desc}")
        tool_list = "\n".join(lines)
    return SYSTEM_PROMPT_TEMPLATE.format(tool_list=tool_list)


async def _run_task_loop(task_id: str, user_id: int, prompt: str) -> None:
    """The detached background loop. Owns its own DB session so it
    survives after the HTTP request that created the task has returned."""
    async with SessionLocal() as db:
        # Resolve user (we have user_id from the request context).
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            _log.error(f"task {task_id}: user {user_id} not found")
            return

        try:
            await _update_task_status(db, task_id, status="running")

            tool_schemas = await _allowed_tool_schemas(db, user_id)

            # If the user hasn't connected any data providers, fail
            # immediately with a clear message rather than let the LLM
            # hallucinate / refuse a useless answer.
            if not tool_schemas:
                msg = (
                    "You haven't connected any data providers yet. "
                    "Open **Settings → Connectors** and connect Google (Gmail + Calendar + Drive) "
                    "to enable background tasks."
                )
                await _append_event(db, task_id, "final_text", {"text": msg})
                await _update_task_status(
                    db, task_id, status="completed", result_md=msg, completed=True,
                )
                await db.commit()
                return

            # Log which tools the agent actually saw — invaluable for
            # debugging "the LLM didn't call X" without forcing the user
            # to share their event log.
            tool_names = [s.get("function", {}).get("name", "?") for s in tool_schemas]
            await _append_event(db, task_id, "step_start", {
                "step": "agent_loop",
                "available_tools": tool_names,
            })
            await db.commit()

            messages: list[dict] = [
                {"role": "system", "content": _build_system_prompt(tool_schemas)},
                {"role": "user", "content": prompt},
            ]

            base_url, api_key = _llm_base_and_key(DEFAULT_PROVIDER)
            http = get_http()
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

            final_text: str | None = None

            for turn in range(MAX_TASK_TURNS):
                # Refresh the row at top of every turn so a cancel request
                # (POST /tasks/{id}/cancel) takes effect on the next iteration.
                fresh = (await db.execute(
                    select(BackgroundTask).where(BackgroundTask.id == task_id)
                )).scalar_one_or_none()
                if fresh is None or fresh.status == "cancelled":
                    await _append_event(db, task_id, "step_start", {"step": "cancelled"})
                    await db.commit()
                    return

                payload: dict[str, Any] = {
                    "model": DEFAULT_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                }
                if tool_schemas:
                    payload["tools"] = tool_schemas
                    # Force a tool call on the first turn so GPT-4o doesn't
                    # bail out with "I can't access your calendar" — even
                    # when the tool list is in the prompt, the model
                    # sometimes ignores it under "auto". After the first
                    # turn we switch to "auto" so the model can synthesize
                    # a final summary from the tool results.
                    payload["tool_choice"] = "required" if turn == 0 else "auto"

                resp = await http.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=90,
                )
                if resp.status_code != 200:
                    text = resp.text[:300]
                    await _append_event(db, task_id, "error", {"http": resp.status_code, "body": text})
                    await _update_task_status(
                        db, task_id, status="failed",
                        error=f"LLM call failed ({resp.status_code})",
                        completed=True,
                    )
                    await db.commit()
                    return

                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                content = msg.get("content")
                tool_calls = msg.get("tool_calls") or []

                # Append assistant message verbatim (with tool_calls) so the
                # next turn can include it in conversation history.
                assistant_message: dict[str, Any] = {"role": "assistant"}
                if content is not None:
                    assistant_message["content"] = content
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)

                if content:
                    await _append_event(db, task_id, "thinking", {"text": content[:4000]})

                # No tool calls → terminal turn.
                if not tool_calls:
                    final_text = content or ""
                    break

                # Execute tool calls. Read-only ones run in parallel via
                # asyncio.gather (the "v1 boss/worker" — multiple finds at
                # once, real worker decomposition later). Destructive ones
                # serialize through the approval gate so we don't surprise-
                # send 4 emails before the user can blink.
                async def _execute_one(tc: dict) -> dict:
                    tc_id = tc.get("id") or _ulid()
                    fn = tc.get("function") or {}
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}

                    if name not in ALL_ALLOWED_TOOLS:
                        await _append_event(db, task_id, "tool_call", {
                            "id": tc_id, "name": name, "args": args, "rejected": True,
                        })
                        return {
                            "tool_call_id": tc_id,
                            "content": f"Tool {name!r} is not available in background tasks.",
                        }

                    # Destructive → park for user approval before executing.
                    if name in DESTRUCTIVE_TOOLS:
                        await _append_event(db, task_id, "approval_needed", {
                            "id": tc_id, "name": name, "args": args,
                            "summary": _summarize_destructive(name, args),
                        })
                        await db.commit()
                        approved, edited_args = await _park_for_approval(
                            task_id, tc_id, APPROVAL_TIMEOUT_S,
                        )
                        if not approved:
                            await _append_event(db, task_id, "approval_resolved", {
                                "id": tc_id, "name": name, "approved": False,
                            })
                            return {
                                "tool_call_id": tc_id,
                                "content": f"User declined to {name}. Stop trying to run it.",
                            }
                        # Merge edited args (only fields the user changed).
                        if edited_args:
                            args = {**args, **edited_args}
                        await _append_event(db, task_id, "approval_resolved", {
                            "id": tc_id, "name": name, "approved": True, "args": args,
                        })

                    await _append_event(db, task_id, "tool_call", {
                        "id": tc_id, "name": name, "args": args,
                    })

                    if _connectors is None:
                        result_str = "connector registry unavailable"
                        ok = False
                    else:
                        try:
                            ok, result = await _connectors.execute(db, user_id, name, args)
                            result_str = result if isinstance(result, str) else json.dumps(result, default=str)
                        except Exception as e:
                            ok = False
                            raw = str(e)
                            if "401" in raw:
                                result_str = (
                                    "Your Google connection has expired or been revoked. "
                                    "Tell the user: open Settings → Connectors, disconnect Google, then reconnect. "
                                    f"(raw: {raw[:200]})"
                                )
                            elif "403" in raw:
                                result_str = (
                                    "Google denied the request — likely an OAuth scope is missing. "
                                    "Tell the user: disconnect and reconnect Google in Settings → Connectors. "
                                    f"(raw: {raw[:200]})"
                                )
                            else:
                                result_str = f"tool exception: {raw[:500]}"

                    await _append_event(db, task_id, "tool_result", {
                        "id": tc_id, "name": name, "ok": ok,
                        "result_preview": (result_str or "")[:1000],
                    })
                    return {"tool_call_id": tc_id, "content": result_str or ""}

                # Run all read-only calls in parallel. Destructive ones are
                # in the same gather but each parks on its own approval gate,
                # so user can approve them in whatever order they want.
                tool_results = await asyncio.gather(
                    *[_execute_one(tc) for tc in tool_calls],
                    return_exceptions=False,
                )
                for tr in tool_results:
                    messages.append({"role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["content"]})
                await db.commit()
            else:
                # Hit MAX_TASK_TURNS without an assistant final response.
                final_text = "Reached the maximum turn limit without producing a summary."

            await _append_event(db, task_id, "final_text", {"text": final_text or ""})
            await _update_task_status(
                db, task_id,
                status="completed",
                result_md=final_text or "",
                completed=True,
            )
            await db.commit()
        except Exception as e:
            _log.exception(f"task {task_id} failed")
            try:
                await _append_event(db, task_id, "error", {"message": str(e)})
                await _update_task_status(
                    db, task_id, status="failed", error=str(e)[:1000], completed=True,
                )
                await db.commit()
            except Exception:
                pass


# ── HTTP endpoints ────────────────────────────────────────────────────────────


class TaskCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)


async def tasks_create(
    body: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a task and fire the agent loop in the background."""
    check_burst(user.id, "background_task", per_hour=BURST_PER_HOUR, per_day=BURST_PER_DAY)
    await check_and_increment(db, user, "command")

    task_id = _ulid()
    db.add(BackgroundTask(
        id=task_id, user_id=user.id, prompt=body.prompt.strip(), status="queued",
    ))
    await db.commit()

    # Fire the loop detached from the request. It opens its own DB session.
    asyncio.create_task(_run_task_loop(task_id, user.id, body.prompt.strip()))
    return {"id": task_id, "status": "queued"}


async def tasks_list(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Most recent 50 tasks for the caller."""
    rows = (await db.execute(
        select(BackgroundTask).where(BackgroundTask.user_id == user.id)
        .order_by(desc(BackgroundTask.created_at)).limit(50)
    )).scalars().all()
    return {
        "tasks": [
            {
                "id": r.id,
                "prompt": r.prompt,
                "status": r.status,
                "result_md": r.result_md,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
    }


async def tasks_get(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Single task + full event log."""
    task = (await db.execute(
        select(BackgroundTask).where(
            BackgroundTask.id == task_id, BackgroundTask.user_id == user.id,
        )
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    events = (await db.execute(
        select(TaskEvent).where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.seq)
    )).scalars().all()
    return {
        "id": task.id,
        "prompt": task.prompt,
        "status": task.status,
        "result_md": task.result_md,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "events": [
            {
                "seq": e.seq,
                "kind": e.kind,
                "data": e.data,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


def _summarize_destructive(name: str, args: dict) -> str:
    """Short human-readable summary of a pending destructive action,
    shown in the approval card."""
    if name == "gmail_send":
        return f"Send email to {args.get('to', '?')} — subject: {(args.get('subject') or '')[:80]}"
    if name == "gmail_reply":
        return f"Reply on thread {args.get('threadId', '?')[:12]}…"
    if name == "gmail_draft":
        return f"Create draft to {args.get('to', '?')} — subject: {(args.get('subject') or '')[:80]}"
    if name == "slack_send_message":
        return f"Post to {args.get('channel', '?')} — {(args.get('text') or '')[:100]}"
    if name == "calendar_create_event":
        return f"Create event '{args.get('title', '?')}' {args.get('start','')} → {args.get('end','')}"
    return f"{name}({', '.join(args.keys())})"


class TaskApproveRequest(BaseModel):
    tool_call_id: str
    approved: bool
    edited_args: dict | None = None


async def tasks_approve(
    task_id: str,
    body: TaskApproveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Approve or reject a pending destructive tool call inside a task."""
    # Sanity: confirm the task belongs to this user.
    task = (await db.execute(
        select(BackgroundTask).where(
            BackgroundTask.id == task_id, BackgroundTask.user_id == user.id,
        )
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    ok = await _resolve_approval(task_id, body.tool_call_id, body.approved, body.edited_args)
    if not ok:
        return {"ok": False, "reason": "no pending gate — likely timed out or already resolved"}
    return {"ok": True}


async def tasks_cancel(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Mark a task as cancelled. The background loop checks this at the top
    of each turn and exits cleanly — there's no mid-LLM-call cancellation."""
    task = (await db.execute(
        select(BackgroundTask).where(
            BackgroundTask.id == task_id, BackgroundTask.user_id == user.id,
        )
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status in ("completed", "failed", "cancelled"):
        return {"ok": True, "already_terminal": True, "status": task.status}
    task.status = "cancelled"
    task.updated_at = datetime.now(timezone.utc)
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "status": "cancelled"}
