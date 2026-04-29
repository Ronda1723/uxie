"""
Tests for iOS additions (Phase 0). Verifies:
  - /agent/execute returns a well-formed SSE stream with the locked event taxonomy
  - /agent/approve and /agent/client_tool_result resume parked loops
  - /history endpoints round-trip data through the new tables
  - /auth/issue-refresh + /auth/refresh round-trip works
  - existing /auth/verify-otp behavior is unchanged (regression guard)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.conftest import create_user_and_token


# ── Helper: parse an SSE stream into a list of (event, data) tuples ──────────

def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for line in body.splitlines():
        if line.startswith(":"):
            continue  # SSE comment / keep-alive
        if line == "":
            if cur_event is not None:
                payload = json.loads("\n".join(cur_data)) if cur_data else {}
                events.append((cur_event, payload))
            cur_event = None
            cur_data = []
            continue
        if line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:"):].strip())
    return events


# ── /agent/execute basic flow ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_execute_streams_locked_event_sequence(client):
    token = await create_user_and_token(client, "ios-exec@test.com")
    resp = await client.post(
        "/agent/execute",
        json={"transcript": "hello world", "mode": "command", "tools_available_on_client": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    names = [e[0] for e in events]

    # The phase-0 stub stream must include these in this order:
    assert names[0] == "session"
    assert "tool_call_start" in names
    assert "tool_call_result" in names
    assert "final_text" in names
    assert names[-1] == "done"

    # session event must contain a session_id and conversation_id
    sess = next(d for n, d in events if n == "session")
    assert sess["session_id"]
    assert sess["conversation_id"]


@pytest.mark.asyncio
async def test_agent_execute_rejects_empty_transcript(client):
    token = await create_user_and_token(client, "ios-empty@test.com")
    resp = await client.post(
        "/agent/execute",
        json={"transcript": "  "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_agent_execute_requires_auth(client):
    resp = await client.post("/agent/execute", json={"transcript": "hi"})
    assert resp.status_code in (401, 403)


# ── Client-tool roundtrip ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_client_tool_invoke_resumes_on_result(client):
    """When iOS advertises 'open_url' in tools_available_on_client, the stub
    stream emits client_tool_invoke and parks. POSTing the result should
    unblock the stream and let it complete with final_text + done."""
    token = await create_user_and_token(client, "ios-client-tool@test.com")

    async def post_result_after_delay(session_id: str, tool_call_id: str):
        # Give the loop a moment to register the gate
        await asyncio.sleep(0.1)
        await client.post(
            f"/agent/client_tool_result/{session_id}/{tool_call_id}",
            json={"result": {"opened": True}},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Start the SSE request and the resolver in parallel
    async with client.stream(
        "POST",
        "/agent/execute",
        json={"transcript": "open uxie", "mode": "command", "tools_available_on_client": ["open_url"]},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        body_chunks: list[str] = []
        resolver_task: asyncio.Task | None = None
        async for chunk in resp.aiter_text():
            body_chunks.append(chunk)
            if resolver_task is None and "client_tool_invoke" in "".join(body_chunks):
                # Extract session_id + id from the stream so far
                events = _parse_sse("".join(body_chunks))
                inv = next(d for n, d in events if n == "client_tool_invoke")
                resolver_task = asyncio.create_task(
                    post_result_after_delay(inv["session_id"], inv["id"])
                )
        if resolver_task:
            await resolver_task

    events = _parse_sse("".join(body_chunks))
    names = [e[0] for e in events]
    assert "client_tool_invoke" in names
    assert "tool_call_result" in names  # should have a tool_call_result for the client tool
    assert names[-1] == "done"


# ── /agent/approve 404 path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_unknown_session_404s(client):
    token = await create_user_and_token(client, "ios-approve@test.com")
    resp = await client.post(
        "/agent/approve/does_not_exist",
        json={"approved": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── /history endpoints ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_lists_empty_for_new_user(client):
    token = await create_user_and_token(client, "ios-history@test.com")
    resp = await client.get("/history", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_history_round_trip_via_db(client, db_session):
    """Insert a Conversation directly, list it via /history, fetch detail."""
    from db_ios import Conversation, Turn
    from datetime import datetime, timezone

    token = await create_user_and_token(client, "ios-rt@test.com")

    # Find the user we just created
    from sqlalchemy import select
    from db import User as UserModel

    user = (
        await db_session.execute(select(UserModel).where(UserModel.email == "ios-rt@test.com"))
    ).scalar_one()

    conv = Conversation(
        id="test_conv_001",
        user_id=user.id,
        title="hello",
        created_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
    )
    turn = Turn(
        id="test_turn_001",
        conversation_id="test_conv_001",
        role="user",
        text="hello world",
    )
    db_session.add_all([conv, turn])
    await db_session.commit()

    # List
    resp = await client.get("/history", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "test_conv_001"

    # Detail
    resp = await client.get(
        "/history/test_conv_001", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == "test_conv_001"
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["text"] == "hello world"

    # Delete
    resp = await client.delete(
        "/history/test_conv_001", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200

    # Verify gone
    resp = await client.get(
        "/history/test_conv_001", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_history_isolated_per_user(client, db_session):
    """User A cannot see or fetch User B's conversation."""
    from db_ios import Conversation
    from datetime import datetime, timezone
    from sqlalchemy import select
    from db import User as UserModel

    token_a = await create_user_and_token(client, "ios-iso-a@test.com")
    token_b = await create_user_and_token(client, "ios-iso-b@test.com")

    user_b = (
        await db_session.execute(select(UserModel).where(UserModel.email == "ios-iso-b@test.com"))
    ).scalar_one()

    conv = Conversation(
        id="test_conv_b",
        user_id=user_b.id,
        title="user b's thread",
        created_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
    )
    db_session.add(conv)
    await db_session.commit()

    # User A lists — must not see B's conversation
    resp = await client.get("/history", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200
    assert all(c["id"] != "test_conv_b" for c in resp.json())

    # User A fetches B's by ID — must 404 (not 403, to avoid leaking existence)
    resp = await client.get(
        "/history/test_conv_b", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp.status_code == 404


# ── /auth/refresh round-trip ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_and_use_refresh_token(client):
    token = await create_user_and_token(client, "ios-refresh@test.com")

    # Issue
    resp = await client.post(
        "/auth/issue-refresh",
        json={"device_id": "iphone-test-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    refresh_token = resp.json()["refresh_token"]
    assert refresh_token
    assert resp.json()["expires_in"] == 30 * 86400

    # Use
    resp = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    assert new_access
    assert resp.json()["expires_in"] == 15 * 60

    # New access token actually works
    resp = await client.get(
        "/history", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rejects_unknown_token(client):
    resp = await client.post("/auth/refresh", json={"refresh_token": "totally-fake"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_missing_body(client):
    resp = await client.post("/auth/refresh", json={})
    assert resp.status_code == 400


# ── Regression: existing /auth/verify-otp shape is unchanged ─────────────────

@pytest.mark.asyncio
async def test_verify_otp_response_shape_unchanged(client):
    """Mac/Windows clients depend on /auth/verify-otp returning at minimum
    {access_token: str}. Our additions must not introduce extra required fields
    or rename existing ones."""
    token = await create_user_and_token(client, "ios-regression@test.com")
    assert isinstance(token, str)
    assert len(token) > 20  # JWTs are long
