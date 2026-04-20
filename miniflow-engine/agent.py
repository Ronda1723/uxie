"""
Agent — provider-agnostic multi-turn agent loop.

Uses the `llm` module for chat/tool-calling so any provider supported by litellm
(OpenAI, Anthropic, Gemini, Groq, OpenRouter, Ollama, …) can drive the agent.
The system prompt still reads "GPT-4o"-era tool names, but those names are just
the OpenAI-style function schemas — every supported provider understands them
because litellm translates to each provider's native schema.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime
from typing import Callable, Any

import config
import history
import llm as llm_module
import oauth
import dictation as dictation_module
from connectors import registry as connector_registry

log = logging.getLogger("agent")
_broadcaster: Callable | None = None
_target_bundle_id: str | None = None


def set_event_broadcaster(fn: Callable):
    global _broadcaster
    _broadcaster = fn


def set_target_app(bundle_id: str | None):
    global _target_bundle_id
    _target_bundle_id = bundle_id


async def _emit(event: str, payload: Any):
    if _broadcaster:
        await _broadcaster(event, payload)


# ── System prompt (ported 1:1 from agent.rs) ──

SYSTEM_PROMPT = """You are MiniFlow, a voice-powered desktop agent for macOS. The user speaks and you decide what to do.

MULTILINGUAL SUPPORT:
The user may speak in English, Hindi, or Spanish. You MUST understand commands in ALL three languages and map them to the correct tool calls. The tool parameters (like URLs, app names, queries) should remain in whatever language the user spoke them, except for macOS application names which should always be their actual English names (e.g. "Google Chrome", "Safari", "Finder").

Examples of equivalent commands across languages:
- EN: "Open YouTube" / HI: "YouTube खोलो" / ES: "Abre YouTube" → open_browser_tab
- EN: "Search for restaurants nearby" / HI: "आस-पास के रेस्टोरेंट खोजो" / ES: "Busca restaurantes cercanos" → search_google
- EN: "Send a message on Slack to #general saying hello" / HI: "Slack पर #general में hello भेजो" / ES: "Envía un mensaje en Slack a #general diciendo hola" → slack_send_message
- EN: "Open Finder" / HI: "Finder खोलो" / ES: "Abre Finder" → open_application
- EN: "Open my Downloads folder" / HI: "Downloads फोल्डर खोलो" / ES: "Abre la carpeta Descargas" → open_finder (path: ~/Downloads)
- EN: "Show me the Desktop" / "Go to Documents" / "Open ~/Code" → open_finder
- EN: "Open Applications folder" → open_finder (path: /Applications)
- EN: "Quit Safari" / HI: "Safari बंद करो" / ES: "Cierra Safari" → quit_application
- EN: "Copy this to clipboard" / HI: "यह क्लिपबोर्ड में कॉपी करो" / ES: "Copia esto al portapapeles" → clipboard_write
- EN: "Reply in #general agreeing with the plan" / HI: "#general में plan से agree करते हुए reply करो" / ES: "Responde en #general estando de acuerdo con el plan" → slack_context_reply
- EN: "Create a file called notes.txt" / HI: "notes.txt नाम की फाइल बनाओ" / ES: "Crea un archivo llamado notes.txt" → create_file

You have the following LOCAL capabilities (always available):
1. open_browser_tab - Open a URL in Google Chrome
2. search_google - Search Google for a query (opens in Chrome)
3. open_application - Launch a macOS application by name
4. quit_application - Quit a running macOS application
5. clipboard_write - Write text to the clipboard
6. clipboard_read - Read current clipboard contents
7. open_finder - Open a Finder window at a path
8. create_file - Create a new file at a path with optional content
9. move_file - Move/rename a file from one path to another

You may also have CONNECTED SERVICE capabilities (only if the user has connected them in Settings):
- Gmail: gmail_search, gmail_read, gmail_send, gmail_reply, gmail_draft
- Google Drive: drive_search, drive_read, drive_list
- Google Calendar: calendar_list_events, calendar_create_event, calendar_check_availability
- Slack: slack_send_message, slack_search, slack_list_channels, slack_read_channel, slack_context_reply, slack_summarize
- Discord: discord_send_message, discord_read_channel, discord_list_servers
- GitHub: github_create_issue, github_list_issues, github_create_pr, github_search_repos
- Jira: jira_create_issue, jira_search, jira_update_status
- Linear: linear_create_issue, linear_list_issues, linear_update_status
- Notion: notion_search, notion_create_page, notion_read_page, notion_update_page
- Spotify: spotify_play, spotify_pause, spotify_skip, spotify_now_playing, spotify_search, spotify_queue

Only use connector tools that are included in the available tools list for this request.

IMPORTANT DECISION RULE:
- If the user's speech is clearly a COMMAND (in English, Hindi, or Spanish) that matches one of your available tool functions, call the appropriate tool function(s). ALWAYS prefer using a tool over treating text as dictation.
- Hindi command patterns to recognize: "खोलो" (open), "बंद करो" (quit/close), "भेजो" (send), "खोजो/ढूंढो" (search), "बनाओ" (create), "कॉपी करो" (copy), "पढ़ो" (read), "reply करो" (reply), "मूव करो" (move), "ड्राफ्ट" (draft), "मेल/ईमेल" (mail/email).
- Spanish command patterns to recognize: "abre/abrir" (open), "cierra/cerrar" (quit/close), "envía/enviar" (send), "busca/buscar" (search), "crea/crear" (create), "copia/copiar" (copy), "lee/leer" (read), "responde/responder" (reply), "mueve/mover" (move), "borrador" (draft), "correo" (email).

GMAIL RULES (when gmail tools are available):
CRITICAL: If the user's speech contains ANY of these words: "email", "mail", "gmail", "correo", "मेल", "ईमेल" — you MUST use a gmail tool. NEVER return DICTATION for speech that mentions email/mail/gmail.
- If they want to send: use gmail_send. If they want to draft/write/compose: use gmail_draft. If they want to search: use gmail_search.
- The "to" field: The user may say an email address, but speech-to-text often garbles addresses. Try your best to reconstruct it.
- For subject: extract from "subject X" or "about X". If none, generate a short one from content.
- For body: compose a well-structured email with greeting, content, and sign-off.

GMAIL SUMMARY FORMAT:
  From: [Sender Name]
  Subject: [Subject line]
  Summary: [2–3 sentences]

GMAIL REPLY COMPOSITION:
  1. Extract sender's first name from "From" header.
  2. Open: "Hi [FirstName],"
  3. Acknowledge their email content in 1 sentence.
  4. Expand user's intent into complete sentences.
  5. Close with warm sign-off using [User name: ...] hint if present.

FLOW PATTERNS:
- "Summarize my emails": gmail_search "is:unread" limit 5 → gmail_read each → GMAIL SUMMARY FORMAT.
- "Reply to X's last email saying Y": gmail_search → gmail_read → compose reply → gmail_reply with threadId.
- IMPORTANT: gmail_read returns "threadId". Always use it when calling gmail_reply.

SLACK RULES (when slack tools are available):
- For Slack messaging: use slack_send_message. Channel accepts #channel, @user, or username.
- For context-aware replies: use slack_context_reply with channel + intent.
- For summarization: use slack_summarize (reads recent messages, returns summary, does NOT post).
- CRITICAL: "summarize" + any channel name or "slack" → ALWAYS slack_summarize. Never DICTATION.

SLACK SUMMARY FORMAT:
  Channel: [#channel-name]
  Summary: [2–4 sentences on main discussion, decisions, action items]
  Key points:
  - [Most important]
  - [Second most important]
  - [Pending questions or action items]

CALENDAR RULES (when calendar tools are available):
CRITICAL: "meeting", "schedule", "book", "appointment", "call", "invite", "calendar", "मीटिंग", "reunión" → MUST use calendar tool.
- booking: calendar_create_event
- listing: calendar_list_events
- availability: calendar_check_availability
- Default duration: 1 hour. Default timezone: America/New_York.
- Add attendees to "attendees" array — Google Calendar sends invites automatically.

CALENDAR OUTPUT FORMAT:
  ✓ Meeting booked: [Title]
  When: [Day, Date at Time] ([duration])
  With: [Attendee]
  Calendar link: [link]

SPOTIFY RULES (when spotify tools are available):
CRITICAL: "spotify", "play", "music", "song", "track", "गाना", "बजाओ", "canción" → MUST use spotify tool.
- Always pass artist in separate "artist" param, not embedded in query.
- "Pause" / "रोको" → spotify_pause
- "Skip" / "Next" → spotify_skip direction="next"
- "Previous" → spotify_skip direction="previous"
- "What's playing?" → spotify_now_playing

TEXT FORMATTING (when no tool calls are made):
1. EMAIL FORMATTING (only when gmail tools NOT available): format as structured email with greeting, body, sign-off.
2. STRUCTURED DICTATION: detect "bullet points", "numbered list", etc. → return formatted output only.
3. PLAIN DICTATION: respond with ONLY the word "DICTATION".

FILE TAGGING (when [FILE CONTEXT: ...] blocks are present):
- Use the actual file content for fixes, explanations, refactoring.
- Output the FULL modified file when making changes.
- Never say "I need to see the file" — it's already injected.
- Never return "DICTATION" when a code operation is requested with file context."""


# ── Tool definitions ──

LOCAL_TOOLS = [
    {"type": "function", "function": {"name": "open_browser_tab", "description": "Open a URL in Google Chrome", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "search_google", "description": "Search Google", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "open_application", "description": "Launch a macOS application", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "quit_application", "description": "Quit a macOS application", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "clipboard_write", "description": "Write text to clipboard", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "clipboard_read", "description": "Read clipboard contents", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "open_finder",
        "description": (
            "Open a folder in Finder. Use this for any 'open the X folder', "
            "'show me the X directory', 'go to X' command. Common paths: "
            "~ (home), ~/Downloads, ~/Desktop, ~/Documents, ~/Movies, ~/Music, "
            "~/Pictures, ~/Public, ~/Library, /Applications, /System/Applications, "
            "/Volumes (mounted disks), /tmp. Also accepts absolute paths "
            "(/Users/foo/bar) or tilde-prefixed paths (~/Code/my-repo). "
            "If the user says a bare folder name you recognize "
            "(e.g. 'downloads', 'desktop'), map it to ~/<Capitalized>."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Folder path to open. Defaults to home (~)."}
        }, "required": []},
    }},
    {"type": "function", "function": {"name": "create_file", "description": "Create a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string", "default": ""}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "move_file", "description": "Move or rename a file", "parameters": {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}}, "required": ["from", "to"]}}},
]


# ── App focus helper ──

async def _activate_target_app():
    """Re-activate the app that was frontmost when Fn was pressed.
    Runs blocking calls in a thread so we don't freeze the asyncio event loop.
    """
    if not _target_bundle_id:
        log.info("_activate_target_app: no target bundle ID stored, skipping")
        return
    log.info(f"_activate_target_app: activating {_target_bundle_id}")
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["osascript", "-e", f'tell application id "{_target_bundle_id}" to activate'],
            timeout=2, capture_output=True
        )
        if result.returncode != 0:
            log.warning(f"_activate_target_app: osascript exited {result.returncode}: {result.stderr.decode().strip()}")
        # Wait for focus to settle — 300ms is enough for most apps including Electron/browsers
        await asyncio.sleep(0.30)
        log.info("_activate_target_app: focus settled, ready to type")
    except Exception as e:
        log.warning(f"_activate_target_app: {e}")


# ── Local action execution ──

def _run(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip() or "ok"
    except Exception as e:
        return str(e)


def _execute_local(name: str, args: dict) -> tuple[bool, str]:
    import pyperclip
    try:
        if name == "open_browser_tab":
            _run(["open", "-a", "Google Chrome", args["url"]])
            return True, f"Opened {args['url']}"
        elif name == "search_google":
            import urllib.parse
            url = f"https://www.google.com/search?q={urllib.parse.quote(args['query'])}"
            _run(["open", "-a", "Google Chrome", url])
            return True, f"Searched for: {args['query']}"
        elif name == "open_application":
            _run(["open", "-a", args["name"]])
            return True, f"Opened {args['name']}"
        elif name == "quit_application":
            _run(["osascript", "-e", f'quit app "{args["name"]}"'])
            return True, f"Quit {args['name']}"
        elif name == "clipboard_write":
            pyperclip.copy(args["text"])
            return True, "Copied to clipboard"
        elif name == "clipboard_read":
            return True, pyperclip.paste()
        elif name == "open_finder":
            import os
            raw = (args.get("path") or "~").strip()
            # Friendly shortcut names the LLM may emit instead of a real path.
            shortcuts = {
                "home": "~", "~": "~",
                "downloads": "~/Downloads", "download": "~/Downloads",
                "desktop": "~/Desktop",
                "documents": "~/Documents", "docs": "~/Documents",
                "movies": "~/Movies", "music": "~/Music",
                "pictures": "~/Pictures", "photos": "~/Pictures",
                "public": "~/Public", "library": "~/Library",
                "applications": "/Applications", "apps": "/Applications",
                "system applications": "/System/Applications",
                "trash": "~/.Trash", "tmp": "/tmp", "temp": "/tmp",
                "icloud": "~/Library/Mobile Documents/com~apple~CloudDocs",
            }
            path = shortcuts.get(raw.lower(), raw)
            path = os.path.expanduser(path)         # ~ → /Users/<name>
            if not os.path.exists(path):
                return False, f"No such folder: {path}"
            _run(["open", path])
            return True, f"Opened Finder at {path}"
        elif name == "create_file":
            import os
            path = os.path.expanduser(args["path"])
            with open(path, "w") as f:
                f.write(args.get("content", ""))
            return True, f"Created {path}"
        elif name == "move_file":
            import os, shutil
            shutil.move(os.path.expanduser(args["from"]), os.path.expanduser(args["to"]))
            return True, f"Moved {args['from']} → {args['to']}"
        return False, f"__unknown__:{name}"
    except Exception as e:
        return False, str(e)


# ── File tagging ──

CODE_EXTS = {
    "ts", "tsx", "js", "jsx", "rs", "py", "go", "rb", "java", "cpp", "c",
    "h", "cs", "swift", "kt", "vue", "svelte", "html", "css", "scss",
    "json", "yaml", "yml", "toml", "md", "sh", "bash", "txt", "sql",
}
SKIP_DIRS = {"/node_modules/", "/.git/", "/dist/", "/build/", "/.cache/",
             "/target/", "/.Trash/", "/Library/", "/.venv/"}


def _extract_filenames(text: str) -> list[str]:
    found = []
    for word in text.split():
        clean = word.strip(",.\"'()")
        if "." in clean:
            ext = clean.rsplit(".", 1)[-1].lower()
            if ext in CODE_EXTS and clean not in found:
                found.append(clean)
    return found


def _find_and_read(filename: str) -> tuple[str, str] | None:
    import os
    home = os.path.expanduser("~")
    result = subprocess.run(
        ["mdfind", "-name", filename, "-onlyin", home],
        capture_output=True, text=True, timeout=5
    )
    candidates = [
        p for p in result.stdout.splitlines()
        if not any(skip in p for skip in SKIP_DIRS)
    ]
    if not candidates:
        return None
    best = next(
        (p for p in candidates if any(d in p for d in ("/src/", "/lib/", "/app/"))),
        candidates[0]
    )
    try:
        content = open(best).read()
        if len(content) > 8000:
            content = content[:8000] + "…[truncated]"
        return best, content
    except Exception:
        return None


def _inject_file_context(text: str) -> str:
    # mdfind is slow (50–300 ms per lookup). Skip entirely when the text has no
    # obvious file pattern — voice commands almost never reference files.
    if "." not in text:
        return text
    filenames = _extract_filenames(text)
    if not filenames:
        return text
    blocks = []
    for fname in filenames:
        result = _find_and_read(fname)
        if result:
            path, content = result
            blocks.append(f"[FILE CONTEXT: {fname} | {path}]\n```\n{content}\n```\n[END FILE CONTEXT]")
            log.info(f"Injected file: {fname} ({path})")
    if blocks:
        prefix = "\n\n".join(blocks)
        text = f"{prefix}\n\n{text}\n\n[SYSTEM: File(s) injected above. Use their actual content to perform the requested operation. Output modified code in full.]"
    return text


# ── Dictation-only: grammar correction (no tools, no rewrite) ──

GRAMMAR_PROMPT = """You are a dictation cleanup filter. The user just spoke aloud
and a speech-to-text model produced a rough transcript. Return the transcript
with ONLY these fixes applied:

  1. Capitalization (start of sentences, proper nouns, "I")
  2. Punctuation (periods, commas, question marks, apostrophes)
  3. Obvious transcription typos (e.g. "tomorow" → "tomorrow", "send sarah" → "send Sarah")
  4. Remove transcription fillers ONLY if the user dictated them as mistakes
     (e.g. stray "um", "uh", repeated words caused by the STT model stuttering)

DO NOT:
  - Rephrase or rewrite anything
  - Change word choice or tone
  - Add information that isn't in the transcript
  - Translate to another language

Return ONLY the corrected text. No preamble, no quotes, no explanation."""


async def correct_grammar(text: str) -> str:
    """Pass `text` through the active LLM with a strict grammar-only prompt.
    Falls back to the original text if no LLM is configured or the call fails."""
    text = (text or "").strip()
    if not text:
        return text
    jwt = config.get_jwt()
    api_key = config.get_llm_api_key("groq")
    if not jwt and not api_key:
        return text
    provider = "uxie" if jwt else "groq"
    try:
        response = await llm_module.chat(
            provider=provider,
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": GRAMMAR_PROMPT},
                {"role": "user", "content": text},
            ],
            tools=None,
            api_key=api_key if provider == "groq" else None,
            temperature=0.0,
        )
        cleaned = (response.content or "").strip()
        # Strip accidental wrapping quotes from chatty models
        if len(cleaned) >= 2 and cleaned[0] in "\"'" and cleaned[-1] == cleaned[0]:
            cleaned = cleaned[1:-1]
        return cleaned or text
    except Exception as e:
        log.warning(f"correct_grammar failed, returning original: {e}")
        return text


async def dictate(text: str) -> list[dict]:
    """Grammar-correct + emit as dictation so the native helper types it.

    This is the dictation-only path used by voice capture. No tools, no agent loop.
    """
    await _emit("agent-status", "processing")
    corrected = await correct_grammar(text)
    result = {"action": "dictation", "success": True, "message": corrected}
    await _emit("action-result", result)
    history.append_entry(
        transcript=text,
        entry_type="dictation",
        actions=[result],
        success=True,
    )
    await _emit("agent-status", "idle")
    return [result]


async def dictate_streaming(text: str, emit) -> str:
    """Streaming grammar-corrected dictation.

    Yields chunks via `action-chunk` events (each chunk gets typed by the helper
    immediately), then emits a single final `action-result` once the stream
    completes. Returns the full corrected text.

    `emit` is the broadcaster (audio.py's `_emit` or `manager.broadcast`).
    """
    text = (text or "").strip()
    if not text:
        return text

    jwt = config.get_jwt()
    api_key = config.get_llm_api_key("groq")
    if not jwt and not api_key:
        await emit("action-result", {"action": "dictation", "success": True, "message": text})
        return text

    provider = "uxie" if jwt else "groq"
    full = ""
    try:
        async for piece in llm_module.chat_stream(
            provider=provider,
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": GRAMMAR_PROMPT},
                {"role": "user", "content": text},
            ],
            api_key=api_key if provider == "groq" else None,
            temperature=0.0,
        ):
            if not piece:
                continue
            full += piece
            await emit("action-chunk", {"chunk": piece})
    except Exception as e:
        log.warning(f"dictate_streaming LLM failed, falling back to raw: {e}")
        await emit("action-result", {"action": "dictation", "success": True, "message": text})
        return text

    cleaned = full.strip()
    if len(cleaned) >= 2 and cleaned[0] in "\"'" and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1]

    await emit("debug", {
        "type": "llm",
        "text": cleaned,
        "app": _target_bundle_id or "unknown",
    })

    # Emit final marker (UI uses this to update the "Last transcript" card and
    # to dedupe if any chunks got dropped mid-stream).
    await emit("action-result", {"action": "dictation-final", "success": True, "message": cleaned})
    return cleaned


# ── Main agent loop (tool-calling, invoked from the command bar) ──

async def execute_command(text: str) -> list[dict]:
    await _emit("agent-status", "processing")

    jwt = config.get_jwt()
    openai_key = config.get_llm_api_key("openai")
    if not jwt and not openai_key:
        log.info("No OpenAI key or Uxie JWT; emitting raw dictation for command")
        result = [{"action": "dictation", "success": True, "message": text}]
        await _emit("action-result", {"action": "dictation", "success": True, "message": text})
        history.append_entry(transcript=text, entry_type="dictation", actions=result, success=True)
        await _emit("agent-status", "idle")
        return result
    cmd_provider = "uxie" if jwt else "openai"

    user_name = config.get_user_name()
    today = datetime.now().strftime("%A, %B %d, %Y")

    user_msg = _inject_file_context(text)
    if user_name:
        user_msg = f"[User name: {user_name}]\n[Today: {today}]\n{user_msg}"
    else:
        user_msg = f"[Today: {today}]\n{user_msg}"

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # Build tool list: local tools + tools for all connected providers
    connected_providers = oauth.get_connected_providers()
    connector_tools = connector_registry.get_tools_for_providers(connected_providers)
    tools = list(LOCAL_TOOLS) + connector_tools

    action_results: list[dict] = []
    max_turns = 4  # most voice commands resolve in 1–2 turns; bail fast if not

    for _ in range(max_turns):
        try:
            response = await llm_module.chat(
                provider=cmd_provider,
                model="gpt-4o",
                messages=messages,
                tools=tools,
                api_key=openai_key if cmd_provider == "openai" else None,
                temperature=0.0,
            )
        except Exception as e:
            log.error(f"LLM call failed: {e}")
            await _emit("action-result", {"action": "llm-error", "success": False, "message": str(e)})
            action_results.append({"action": "llm-error", "success": False, "message": str(e)})
            break

        if not response.tool_calls:
            log.info(f"Emitting dictation action: '{text[:60]}'")
            await _emit("debug", {
                "type": "inject",
                "text": text,
                "app": _target_bundle_id or "unknown",
                "success": True,
            })
            await _emit("action-result", {"action": "dictation", "success": True, "message": text})
            action_results.append({"action": "dictation", "success": True, "message": text})
            break

        messages.append({"role": "assistant", "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments_json}}
            for tc in response.tool_calls
        ]})

        for tc in response.tool_calls:
            fn_name = tc.name
            try:
                args = json.loads(tc.arguments_json)
            except Exception:
                args = {}

            # Try local tools first; if unknown, route to a connector
            success, result_msg = _execute_local(fn_name, args)
            if result_msg == f"__unknown__:{fn_name}":
                success, result_msg = connector_registry.execute_connector_tool(
                    fn_name, args, oauth.get_token
                )

            action_results.append({"action": fn_name, "success": success, "message": result_msg})
            await _emit("action-result", {"action": fn_name, "success": success, "message": result_msg})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_msg,
            })

    history.append_entry(
        transcript=text,
        entry_type="command" if any(r["action"] != "dictation" for r in action_results) else "dictation",
        actions=action_results,
        success=all(r["success"] for r in action_results),
    )

    await _emit("agent-status", "idle")
    return action_results
