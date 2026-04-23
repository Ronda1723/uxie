"""
Multi-agent orchestrator — boss + parallel workers.

When a command touches multiple MCP connectors (e.g. "search GitHub issues AND post to Slack"),
the boss decomposes it into sub-tasks, workers run in parallel via asyncio.gather(),
and the boss synthesizes the results into a final action.

Single-connector and local-only commands bypass the orchestrator entirely.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Any

import llm as llm_module
import config
import mcp_client
import oauth
from connectors import registry as connector_registry

log = logging.getLogger("orchestrator")

LOCAL_TOOL_NAMES = {
    "open_browser_tab", "search_google", "open_application", "quit_application",
    "clipboard_write", "clipboard_read", "open_finder", "create_file", "move_file",
}

# Playwright tools are local-ish (always-on MCP server, not user-configured)
PLAYWRIGHT_SERVER = "playwright"

DECOMPOSE_PROMPT = """You are a task planner for a voice assistant. The user gave a command that involves multiple services.
Break it into sub-tasks, one per MCP server. Reply with a JSON array, each item:
  {"server": "<server_id>", "task": "<what this worker should do>", "tools": ["<tool_name>", ...]}

Available MCP servers: playwright (browser automation), github, slack, linear, notion.
Only include servers that are genuinely needed. If a step needs output from a previous step, mark it with "depends_on": "<server_id>".
Return ONLY the JSON array. No explanation."""

SYNTHESIZE_PROMPT = """You are a voice assistant finishing a multi-step task.
The workers have completed their sub-tasks and returned results below.
Based on these results, decide what final action to take (if any) and reply to the user concisely.
If you need to execute one more tool call, do so. Otherwise just summarize what was done."""


async def _route_tool(name: str, args: dict) -> tuple[bool, str]:
    """Three-tier routing: local → OAuth connector → MCP server."""
    import agent as _agent
    success, result = _agent._execute_local(name, args)
    if result == f"__unknown__:{name}":
        success, result = connector_registry.execute_connector_tool(name, args, oauth.get_token)
    if not success and "No connector found" in result:
        success, result = await mcp_client.call_tool(name, args)
    return success, result


def _server_for_tool(tool_name: str) -> str | None:
    """Return the MCP server_id for a tool name, using the live tool→server map."""
    mgr = mcp_client.get_manager()
    return mgr._tools.get(tool_name)


def _servers_needed(tools: list[dict]) -> set[str]:
    """Return the set of MCP server IDs referenced in a tool list (excluding local tools)."""
    seen: set[str] = set()
    for t in tools:
        name = t.get("function", {}).get("name", "")
        if name in LOCAL_TOOL_NAMES:
            continue
        server = _server_for_tool(name)
        if server and server != PLAYWRIGHT_SERVER:
            seen.add(server)
    return seen


def should_orchestrate(command: str, tools: list[dict]) -> bool:
    """Return True if the command involves 2+ distinct user-configured MCP connectors."""
    return len(_servers_needed(tools)) >= 2


async def run(
    text: str,
    tools: list[dict],
    emit: Callable,
    approval_gate: Callable,
) -> list[dict]:
    """
    Boss + parallel worker execution.
    Returns a list of action result dicts (same shape as execute_command).
    """
    jwt = config.get_jwt()
    openai_key = config.get_llm_api_key("openai")
    provider = "uxie" if jwt else "openai"
    api_key = openai_key if provider == "openai" else None

    # ── Turn 1: Boss decomposes the command ──────────────────────────────────
    log.info(f"Orchestrator: decomposing '{text[:80]}'")
    try:
        decompose_resp = await llm_module.chat(
            provider=provider,
            model="gpt-4o",
            messages=[
                {"role": "system", "content": DECOMPOSE_PROMPT},
                {"role": "user", "content": text},
            ],
            api_key=api_key,
            temperature=0.0,
        )
        raw = (decompose_resp.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        sub_tasks: list[dict] = json.loads(raw)
    except Exception as e:
        log.error(f"Orchestrator decompose failed: {e}")
        return [{"action": "orchestrator-error", "success": False, "message": str(e)}]

    log.info(f"Orchestrator: {len(sub_tasks)} sub-tasks: {[t.get('server') for t in sub_tasks]}")

    # ── Turn 2: Run workers in parallel ──────────────────────────────────────
    async def _run_worker(sub_task: dict) -> dict:
        server = sub_task.get("server", "unknown")
        task_desc = sub_task.get("task", "")

        # Give each worker only the tools for its server + local tools
        worker_tools = [
            t for t in tools
            if _server_for_tool(t.get("function", {}).get("name", "")) == server
            or t.get("function", {}).get("name", "") in LOCAL_TOOL_NAMES
        ]
        await emit("agent-status", f"worker:{server}")
        log.info(f"Worker [{server}]: starting — {task_desc[:60]}")

        try:
            resp = await llm_module.chat(
                provider=provider,
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"You are a {server} specialist. Complete this task: {task_desc}. Use the available tools. Return a brief summary of what you found or did."},
                    {"role": "user", "content": text},
                ],
                tools=worker_tools or None,
                api_key=api_key,
                temperature=0.0,
            )
        except Exception as e:
            log.error(f"Worker [{server}] failed: {e}")
            return {"server": server, "status": "error", "data": str(e), "actions_taken": []}

        actions_taken = []
        msgs = [
            {"role": "system", "content": f"You are a {server} specialist. Complete: {task_desc}"},
            {"role": "user", "content": text},
        ]
        if resp.tool_calls:
            msgs.append({"role": "assistant", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments_json}}
                for tc in resp.tool_calls
            ]})

        for tc in (resp.tool_calls or []):
            try:
                args = json.loads(tc.arguments_json)
            except Exception:
                args = {}

            import agent as _agent
            if tc.name in _agent.APPROVAL_REQUIRED_TOOLS:
                approved = await approval_gate(tc.name, args)
                if not approved:
                    actions_taken.append({"tool": tc.name, "success": False, "result": "Cancelled"})
                    continue

            success, result = await _route_tool(tc.name, args)
            actions_taken.append({"tool": tc.name, "success": success, "result": result})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # Final worker summary turn
        if resp.tool_calls and msgs[-1]["role"] == "tool":
            try:
                final = await llm_module.chat(
                    provider=provider, model="gpt-4o",
                    messages=msgs, api_key=api_key, temperature=0.0,
                )
                summary = (final.content or "").strip()
            except Exception:
                summary = "; ".join(a["result"] for a in actions_taken)
        else:
            summary = (resp.content or "").strip()

        log.info(f"Worker [{server}]: done — {summary[:80]}")
        return {"server": server, "status": "done", "data": summary, "actions_taken": actions_taken}

    worker_results = await asyncio.gather(*[_run_worker(t) for t in sub_tasks])

    # ── Turn 3: Boss synthesizes ──────────────────────────────────────────────
    context_block = "\n\n".join(
        f"[{r['server']} worker — {r['status']}]\n{r['data']}"
        for r in worker_results
    )
    await emit("agent-status", "processing")
    try:
        synth_resp = await llm_module.chat(
            provider=provider,
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYNTHESIZE_PROMPT},
                {"role": "user", "content": f"Original command: {text}\n\nWorker results:\n{context_block}"},
            ],
            tools=tools,
            api_key=api_key,
            temperature=0.0,
        )
    except Exception as e:
        log.error(f"Orchestrator synthesize failed: {e}")
        return [{"action": "orchestrator-error", "success": False, "message": str(e)}]

    action_results: list[dict] = []

    for tc in (synth_resp.tool_calls or []):
        try:
            args = json.loads(tc.arguments_json)
        except Exception:
            args = {}
        import agent as _agent
        if tc.name in _agent.APPROVAL_REQUIRED_TOOLS:
            approved = await approval_gate(tc.name, args)
            if not approved:
                action_results.append({"action": tc.name, "success": False, "message": "Cancelled by user"})
                await emit("action-result", action_results[-1])
                continue

        success, result_msg = await _route_tool(tc.name, args)
        action_results.append({"action": tc.name, "success": success, "message": result_msg})
        await emit("action-result", action_results[-1])

    summary = (synth_resp.content or "").strip()
    if summary:
        action_results.append({"action": "summary", "success": True, "message": summary})
        await emit("action-result", {"action": "summary", "success": True, "message": summary})

    await emit("agent-status", "idle")
    return action_results
