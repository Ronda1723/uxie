"""Connector registry — metadata + tool/module lookup."""

from __future__ import annotations
from typing import Any

# ── Connector metadata ──

CONNECTORS = [
    {"id": "google",   "display_name": "Gmail / Calendar / Drive"},
    {"id": "slack",    "display_name": "Slack"},
    {"id": "discord",  "display_name": "Discord"},
    {"id": "github",   "display_name": "GitHub"},
    {"id": "jira",     "display_name": "Jira"},
    {"id": "linear",   "display_name": "Linear"},
    {"id": "notion",   "display_name": "Notion"},
    {"id": "spotify",  "display_name": "Spotify"},
]


def list_connectors() -> list:
    return CONNECTORS


# ── Provider → module mapping ──
# Imported lazily inside functions to avoid circular imports at module level.

def _modules() -> dict:
    from . import google, slack, discord, github, jira, linear, notion, spotify
    return {
        "google":  google,
        "slack":   slack,
        "discord": discord,
        "github":  github,
        "jira":    jira,
        "linear":  linear,
        "notion":  notion,
        "spotify": spotify,
    }


def get_tools_for_providers(providers: list[str]) -> list:
    """Return the combined GPT-4o tool list for all connected providers."""
    mods = _modules()
    tools = []
    for p in providers:
        mod = mods.get(p)
        if mod and hasattr(mod, "TOOLS"):
            tools.extend(mod.TOOLS)
    return tools


def execute_connector_tool(tool_name: str, args: dict, token_fn) -> tuple[bool, str]:
    """
    Route a tool call to the correct connector module.
    token_fn(provider) → token dict
    Returns (success, message).
    """
    # Map tool name prefix → provider
    PREFIX_MAP = {
        "gmail_": "google",
        "calendar_": "google",
        "drive_": "google",
        "slack_": "slack",
        "discord_": "discord",
        "github_": "github",
        "jira_": "jira",
        "linear_": "linear",
        "notion_": "notion",
        "spotify_": "spotify",
    }
    provider = None
    for prefix, prov in PREFIX_MAP.items():
        if tool_name.startswith(prefix):
            provider = prov
            break

    if not provider:
        return False, f"No connector found for tool: {tool_name}"

    token = token_fn(provider)
    if not token:
        return False, f"{provider} is not connected. Please connect it in Settings."

    mods = _modules()
    mod = mods.get(provider)
    if not mod:
        return False, f"Connector module not found: {provider}"

    return mod.execute(tool_name, args, token)
