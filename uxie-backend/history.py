"""
Cross-device conversation history for iOS. New endpoints, no edits to existing
ones. Mac/Windows desktop clients ignore these.

Endpoints:
  GET    /history?limit=50             — list current user's conversations
  GET    /history/{conversation_id}    — full thread with turns
  DELETE /history/{conversation_id}    — user-initiated deletion (cascades turns)
"""

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import current_user
from db import User, get_db
from db_ios import Conversation, Turn


async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.last_active_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "last_active_at": c.last_active_at.isoformat(),
        }
        for c in rows
    ]


async def conversation_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "not found")

    turns = (
        await db.execute(
            select(Turn)
            .where(Turn.conversation_id == conversation_id)
            .order_by(Turn.created_at)
        )
    ).scalars().all()

    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "last_active_at": conv.last_active_at.isoformat(),
        "turns": [
            {
                "id": t.id,
                "role": t.role,
                "text": t.text,
                "tool_calls": t.tool_calls_json,
                "tool_call_id": t.tool_call_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in turns
        ],
    }


async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "not found")
    await db.delete(conv)
    await db.commit()
    return {"ok": True}
