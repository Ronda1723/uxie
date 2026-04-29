"""
Server-side connector registry.

Each connector module exports:
  PROVIDER       — string identifier matching db_ios.OAuthToken.provider
  TOOLS          — list[dict] of OpenAI tool schemas
  execute(name, args, token, http) — async function returning (ok: bool, result: str|dict)

The agent loop in agent.py asks `connectors.tool_schemas(db, user_id)` for the
list of tools the user has connected (i.e. has a non-revoked OAuthToken row
for), and `connectors.execute(db, user_id, name, args)` to dispatch.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db_ios import OAuthToken
from proxy import get_http

from . import slack as _slack

# Registry: provider name → module
_PROVIDERS = {
    _slack.PROVIDER: _slack,
    # Phase 0.7+: google, github, notion, linear, jira, discord, spotify
}

# Reverse: tool name → provider name (built lazily on import)
_TOOL_TO_PROVIDER: dict[str, str] = {}
for _provider, _mod in _PROVIDERS.items():
    for _t in _mod.TOOLS:
        _TOOL_TO_PROVIDER[_t["function"]["name"]] = _provider


def all_tool_names() -> set[str]:
    """All tool names across all registered connectors. Used by agent.py to
    decide whether a tool call should be dispatched server-side."""
    return set(_TOOL_TO_PROVIDER.keys())


async def tool_schemas_for_user(db: AsyncSession, user_id: int) -> list[dict]:
    """Return tool schemas only for providers the user has connected.
    Disconnected providers' tools are NOT advertised to the LLM."""
    stmt = select(OAuthToken.provider).where(OAuthToken.user_id == user_id)
    rows = (await db.execute(stmt)).scalars().all()
    connected = set(rows)
    schemas: list[dict] = []
    for provider, mod in _PROVIDERS.items():
        if provider in connected:
            schemas.extend(mod.TOOLS)
    return schemas


async def get_token(db: AsyncSession, user_id: int, provider: str) -> OAuthToken | None:
    stmt = select(OAuthToken).where(
        OAuthToken.user_id == user_id, OAuthToken.provider == provider
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def execute(
    db: AsyncSession, user_id: int, name: str, args: dict[str, Any]
) -> tuple[bool, Any]:
    """Dispatch a connector tool call. Returns (ok, result-or-error-string)."""
    provider = _TOOL_TO_PROVIDER.get(name)
    if not provider:
        return False, f"no connector registered for tool: {name}"
    mod = _PROVIDERS[provider]
    token = await get_token(db, user_id, provider)
    if token is None:
        return False, f"user has not connected {provider}"
    return await mod.execute(name, args, token, get_http())
