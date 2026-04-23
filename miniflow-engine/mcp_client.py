"""
MCP Client Manager — connects to MCP servers as subprocesses and exposes
their tools to the agent in OpenAI function-calling format.

Each connector (GitHub, Slack, Linear, Notion, Playwright) runs as a separate
MCP server process. This module manages their lifecycle and routes tool calls
to the right server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

log = logging.getLogger("mcp_client")

# Common Node.js / Docker locations that GUI apps miss when launched outside a shell.
_EXTRA_PATH_DIRS = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/share/npm/bin",
]

def _gui_safe_path() -> str:
    current = os.environ.get("PATH", "")
    extras = [d for d in _EXTRA_PATH_DIRS if d not in current]
    return ":".join(extras + [current]) if extras else current

# ── Server definitions ────────────────────────────────────────────────────────

SERVER_DEFS = {
    "playwright": {
        "display": "Browser (Playwright)",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "env_keys": [],  # no credentials needed
        "always_on": True,  # start automatically, no setup needed
    },
    "github": {
        "display": "GitHub",
        "command": "docker",
        "args": ["run", "-i", "--rm",
                 "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                 "ghcr.io/github/github-mcp-server", "stdio"],
        "env_keys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "always_on": False,
    },
    "linear": {
        "display": "Linear",
        "command": "npx",
        "args": ["-y", "linear-mcp"],
        "env_keys": ["LINEAR_API_KEY"],
        "always_on": False,
    },
    "notion": {
        "display": "Notion",
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env_keys": ["NOTION_API_TOKEN"],
        "always_on": False,
    },
}

# ── Config helpers ────────────────────────────────────────────────────────────

def _mcp_config_path():
    import config
    return config.CONFIG_DIR / "mcp_credentials.json"

def get_credentials() -> dict:
    try:
        with open(_mcp_config_path()) as f:
            return json.load(f)
    except Exception:
        return {}

def save_credentials(creds: dict):
    path = _mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(creds, f, indent=2)

def set_credential(server: str, key: str, value: str):
    creds = get_credentials()
    if server not in creds:
        creds[server] = {}
    creds[server][key] = value
    save_credentials(creds)

def get_configured_servers() -> list[str]:
    """Return list of server IDs that have all required credentials set."""
    creds = get_credentials()
    configured = []
    for sid, defn in SERVER_DEFS.items():
        if defn.get("always_on"):
            configured.append(sid)
            continue
        server_creds = creds.get(sid, {})
        if all(k in server_creds and server_creds[k] for k in defn["env_keys"]):
            configured.append(sid)
    return configured

# ── MCP Manager ───────────────────────────────────────────────────────────────

class MCPManager:
    def __init__(self):
        self._sessions: dict[str, Any] = {}  # server_id → ClientSession
        self._tools: dict[str, str] = {}     # tool_name → server_id
        self._tool_schemas: list[dict] = []  # OpenAI-format tool list
        self._lock = asyncio.Lock()

    async def start(self):
        """Start all configured MCP servers."""
        servers = get_configured_servers()
        if not servers:
            log.info("No MCP servers configured")
            return
        await asyncio.gather(*[self._start_server(sid) for sid in servers],
                             return_exceptions=True)
        await self._rebuild_tool_index()
        log.info(f"MCP ready: {len(self._tool_schemas)} tools from {len(self._sessions)} servers")

    async def restart_server(self, server_id: str):
        """Start or restart a single server (called after credentials are saved)."""
        async with self._lock:
            await self._stop_server(server_id)
        await self._start_server(server_id)
        await self._rebuild_tool_index()

    async def stop_all(self):
        for sid in list(self._sessions.keys()):
            await self._stop_server(sid)

    def get_tools(self) -> list[dict]:
        """Return all MCP tools in OpenAI function-calling format."""
        return list(self._tool_schemas)

    async def call_tool(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Route a tool call to the correct MCP server."""
        server_id = self._tools.get(tool_name)
        if not server_id:
            return False, f"__unknown__:{tool_name}"
        session = self._sessions.get(server_id)
        if not session:
            return False, f"MCP server '{server_id}' is not running"
        try:
            result = await session.call_tool(tool_name, args)
            # Extract text content from MCP result
            text_parts = []
            for content in (result.content or []):
                if hasattr(content, "text"):
                    text_parts.append(content.text)
                elif hasattr(content, "data"):
                    text_parts.append(f"[image data: {len(content.data)} bytes]")
            return True, "\n".join(text_parts) or "Done"
        except Exception as e:
            log.error(f"MCP tool call {tool_name} failed: {e}")
            return False, str(e)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _start_server(self, server_id: str):
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        defn = SERVER_DEFS.get(server_id)
        if not defn:
            log.warning(f"Unknown MCP server: {server_id}")
            return

        # Build env with augmented PATH (GUI apps don't inherit shell PATH)
        env = dict(os.environ)
        env["PATH"] = _gui_safe_path()

        # Check command is available
        cmd = defn["command"]
        if not shutil.which(cmd, path=env["PATH"]):
            log.warning(f"MCP server '{server_id}' requires '{cmd}' which is not installed")
            return

        # Inject credentials
        creds = get_credentials().get(server_id, {})
        for key in defn["env_keys"]:
            val = creds.get(key, "")
            if val:
                env[key] = val

        params = StdioServerParameters(
            command=cmd,
            args=defn["args"],
            env=env,
        )

        try:
            log.info(f"Starting MCP server: {server_id}")
            # Store context managers so we can close them later
            cm_client = stdio_client(params)
            read, write = await cm_client.__aenter__()
            cm_session = ClientSession(read, write)
            session = await cm_session.__aenter__()
            await session.initialize()
            self._sessions[server_id] = session
            # Store context managers for cleanup
            self._sessions[f"_cm_{server_id}"] = (cm_client, cm_session)
            log.info(f"MCP server '{server_id}' started")
        except Exception as e:
            log.error(f"Failed to start MCP server '{server_id}': {e}")

    async def _stop_server(self, server_id: str):
        cms = self._sessions.pop(f"_cm_{server_id}", None)
        self._sessions.pop(server_id, None)
        if cms:
            cm_client, cm_session = cms
            try:
                await cm_session.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await cm_client.__aexit__(None, None, None)
            except Exception:
                pass

    async def _rebuild_tool_index(self):
        """Rebuild the tool name → server mapping and OpenAI-format schema list."""
        self._tools = {}
        self._tool_schemas = []
        for server_id, session in self._sessions.items():
            if server_id.startswith("_cm_"):
                continue
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    self._tools[tool.name] = server_id
                    self._tool_schemas.append(_to_openai_tool(tool))
            except Exception as e:
                log.error(f"Failed to list tools from '{server_id}': {e}")


def _to_openai_tool(mcp_tool) -> dict:
    """Convert an MCP Tool object to OpenAI function-calling format."""
    schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}
    # Remove keys OpenAI doesn't accept
    schema.pop("additionalProperties", None)
    schema.pop("$schema", None)
    return {
        "type": "function",
        "function": {
            "name": mcp_tool.name,
            "description": mcp_tool.description or "",
            "parameters": schema,
        }
    }


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: MCPManager | None = None


def get_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


async def start():
    await get_manager().start()


async def stop():
    if _manager:
        await _manager.stop_all()


async def restart_server(server_id: str):
    await get_manager().restart_server(server_id)


def get_tools() -> list[dict]:
    return get_manager().get_tools()


async def call_tool(name: str, args: dict) -> tuple[bool, str]:
    return await get_manager().call_tool(name, args)


def get_server_status() -> list[dict]:
    """Return status of all servers for the Settings UI."""
    mgr = get_manager()
    creds = get_credentials()
    result = []
    for sid, defn in SERVER_DEFS.items():
        server_creds = creds.get(sid, {})
        is_running = sid in mgr._sessions
        is_configured = defn.get("always_on") or all(
            k in server_creds and server_creds[k] for k in defn["env_keys"]
        )
        result.append({
            "id": sid,
            "display": defn["display"],
            "always_on": defn.get("always_on", False),
            "env_keys": defn["env_keys"],
            "configured": is_configured,
            "running": is_running,
            "credentials": {k: bool(server_creds.get(k)) for k in defn["env_keys"]},
        })
    return result
