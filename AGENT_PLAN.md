# Uxie Agent System — Build Plan

A voice-first agentic system for Mac and Windows. Builds on Uxie's existing single-turn agent loop, scales it to long-running multi-step tasks, adds cross-platform tool parity, persistent session state, background spawning, and an optional "teaching" mode that drags the system cursor (no fake sprite).

This document is the source of truth. It's opinionated where Clicky's approach is good but not right for Uxie, and it pushes back on the multi-agent-orchestrator complexity until we have evidence we need it.

---

## Reality check first

Before any new phases, be honest about where Uxie already is:

| Capability | Today | What "Clicky-class" needs |
|---|---|---|
| Voice → text | Deepgram Nova-3 streaming, ephemeral key | Same — already there |
| LLM tool-calling | OpenAI-format tools via `/llm/chat` on Railway | Same — already there. Don't switch to Claude/Anthropic; OpenAI tool-calling is fine. |
| Loop | `agent.py:798-830`, **max 4 turns** | Bump to 50, add streaming progress events |
| Tool registry | `_execute_local` (Mac-only) + connectors | Cross-platform parity, return-typed errors, "not_supported" sentinel |
| State across turns | In-memory `messages` array, lost on quit | Persistent SQLite context bag |
| Background tasks | None — UI blocks during loop | Detached agent runs with progress streaming |
| Memory across sessions | None | Vector store of facts + preferences |
| Cursor pointing | None | Teacher-mode cursor drag (system cursor, no overlay sprite) |
| Multi-agent | None | **Skip until evidence demands it** (see §6) |

The cheap wins are turn-cap + cross-platform tool parity + persistent context. The expensive items (vector memory, multi-agent orchestration, cursor teaching) are real features but should be Phase 4+, not v1.

---

## §1. Architecture (5 layers, not 7)

The other agent proposed 7 layers. That's over-decorated. We need 5:

```
┌────────────────────────────────────────────────────────────────┐
│ Voice + UI            existing Uxie panel + status updates    │
├────────────────────────────────────────────────────────────────┤
│ Agent runtime         multi-turn loop, streaming progress      │
├────────────────────────────────────────────────────────────────┤
│ Context bag           SQLite-typed entries within a session    │
├────────────────────────────────────────────────────────────────┤
│ Tool registry         cross-platform impls behind one name     │
├────────────────────────────────────────────────────────────────┤
│ Transport             Railway proxy (unchanged dumb pipe)      │
└────────────────────────────────────────────────────────────────┘
```

The Railway proxy stays a pure key-holding LLM proxy. Everything else lives on-device — same call Farza made for Clicky and the right call for the same reasons (AppleScript, COM, xcodebuild, cursor control can't be remoted).

**No "Memory" or "Orchestrator" layers in v1.** Memory is a tool the agent calls. Multi-agent is a Phase 5 question with a hard precondition (see §6).

---

## §2. Phase 0 — Foundations (1 week)

Goal: prove the agentic loop end-to-end with capabilities we already have. Zero new features for users; this is plumbing.

### Tasks

1. **Lift the turn cap**: `agent.py` `MAX_TURNS = 4` → 50. Add per-iteration timeout (30s) and total session budget (5 min). Both bounded for cost control.

2. **Streaming progress events**: today the loop is silent until done. Emit one event per turn:
   ```python
   await _emit("agent-progress", {
     "turn": n,
     "thinking": "...",     # optional, surfaced from assistant message before tool calls
     "tool_call": {"name": fn_name, "args": args},
   })
   ```
   Renderer shows the latest line in the existing Home panel — no new UI.

3. **Cancel button**: holding `fn` again during a long-running command cancels. Implementation: an `asyncio.Event` checked before each turn.

4. **Persistent message log per session**: every loop turn appends to `~/miniflow/agent_sessions/<session_id>.json`. If app crashes mid-loop, next launch sees the dangling session and can resume or discard.

5. **Trigger UX**: keep the existing hotkey. The "is this a long-running task?" decision is made by the LLM — if turn 1 emits a multi-step plan or a tool-call that obviously takes >30s, the renderer switches to a "running in background" affordance. Don't add a magic "uxie agent" voice prefix; users won't remember it.

### Done when

`"summarize the contents of every PDF in my Downloads folder and email me the summary"` runs to completion across multiple turns, with progress visible in the panel and a working cancel button.

---

## §3. Phase 1 — Cross-platform tool registry (1.5 weeks)

Goal: Mac and Windows expose the same tool names. Existing `_execute_local` is Mac-only and returns plain strings; we need typed results.

### New protocol

```python
class Tool:
    name: str
    description: str          # what the LLM sees
    schema: dict              # JSON-schema for args
    platforms: list[str]      # ["darwin", "win32"]
    requires_approval: bool   # gates through approval widget
    async def execute(self, args, ctx) -> ToolResult: ...

@dataclass
class ToolResult:
    status: Literal["success", "failure", "not_supported", "needs_confirmation"]
    output: Any                            # JSON-serializable
    context_writes: list[ContextEntry]     # see §4
    error_reason: str | None
    retry_after_seconds: float | None      # optional hint to model
```

Tools never raise to the model. Failures return structured results so the LLM can read the error and recover.

### Tool table (Phase 1 minimum)

| Tool | Mac impl | Win impl | Approval |
|---|---|---|---|
| `open_application` | `subprocess.run(["open", "-a", name])` | `subprocess.run(["start", "", name])` via shell | no |
| `open_url` | `open <url>` | `start <url>` | no |
| `read_file(path)` | stdlib | stdlib | no |
| `write_file(path, content)` | stdlib (sandboxed to working dir) | same | yes if outside working dir |
| `list_dir(path)` | stdlib | stdlib | no |
| `shell_exec(cmd, cwd, timeout)` | `Process` | `Process` | yes |
| `create_reminder(title, due)` | EventKit | Microsoft Graph (when signed in) or notSupported v1 | no |
| `create_calendar_event(...)` | EventKit | Microsoft Graph or notSupported v1 | yes |
| `create_note(title, body)` | AppleScript → Notes.app | `.txt` in `~/Documents/Uxie Notes` (no native fallback) | no |
| `applescript(source)` | `NSAppleScript` | notSupported | yes |
| `powershell(source)` | notSupported | spawn | yes |
| `screenshot(monitor?)` | ScreenCaptureKit | Graphics.Capture / GDI | no |
| `clipboard_read` / `clipboard_write` | pyperclip | pyperclip | no |

### Key calls

- **Cross-platform from day one**, not Mac-then-port. Each tool is a single source file with two implementation methods. Forces interface discipline.
- **`not_supported` is a first-class result.** When Windows can't do something, return that — the LLM sees it and can suggest alternatives ("I can create a `.txt` note instead of a OneNote page — would you like that?").
- **`requires_approval`** flag wires into the existing approval gate ([`agent.py:32-86`](miniflow-engine/agent.py#L32-L86)). No new approval system.
- **Sandboxed working directory** per session: `~/Library/Application Support/Uxie/agents/<session_id>/` (Mac) or `%APPDATA%\Uxie\agents\<session_id>\` (Win). Filesystem tools default to this; writes outside trip the approval gate.

### What to **not** add in Phase 1

- ❌ `click(x,y)`, `type(text)`, `keypress` (synthetic input). Brittle, breaks when windows shift, replaced 90% of the time by AppleScript / EventKit / COM. Add only if a specific user demand surfaces.
- ❌ Browser tools. Phase 3.
- ❌ `xcodebuild`. Phase 4 (or never).

### Done when

`"open Spotify and play Bicep's Glue"` works on both platforms (Mac via AppleScript, Windows via COM if Spotify desktop is installed, fallback to `open_url` with `spotify:track:...`).

---

## §4. Phase 2 — Persistent context bag (1 week)

Goal: agents can write structured findings during a session that other tool calls (or future turns) can query. Survives crashes.

### Schema

```sql
CREATE TABLE session (
    id          TEXT PRIMARY KEY,
    user_intent TEXT NOT NULL,
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER,
    status      TEXT NOT NULL  -- 'running', 'completed', 'failed', 'cancelled'
);

CREATE TABLE context_entries (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES session(id),
    type        TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,    -- JSON
    summary     TEXT,             -- one-line for LLM consumption
    tags        TEXT,             -- JSON array
    confidence  REAL DEFAULT 1.0,
    ttl_seconds INTEGER,
    created_at  INTEGER NOT NULL
);

CREATE INDEX idx_session_type ON context_entries(session_id, type);
```

### Standard `type` taxonomy (lock these)

`file_written` · `file_read` · `dir_listed` · `app_opened` · `app_state` · `url_visited` · `web_facts` · `user_preference` · `task_completed` · `task_failed` · `error` · `pending_confirmation`

Don't let it be a free-for-all — strict taxonomy = strict observability.

### How the LLM uses it

A new tool: `recall(types?, tags?, since_seconds?, limit=10) -> list[ContextEntry]`. The LLM calls this when it needs to remember what it did earlier in the session. Every other tool's `ToolResult.context_writes` is auto-inserted.

The system prompt gets one paragraph telling the model the bag exists and when to use `recall`. Don't dump the whole bag into context — that defeats the point.

### Done when

`"download the latest invoice from each vendor email this week and put them in a folder called Q2-invoices"` survives across 30+ tool calls and an app restart, without re-doing finished steps.

---

## §5. Phase 3 — Web research tools (1 week)

Goal: enable the influencer-CSV / "find X on the web" demos.

### Decision: hosted browser, not bundled Playwright

Bundling Chromium adds ~150MB to the installer. We just shipped a 151MB DMG; doubling it for one feature is wrong. Use a hosted browser provider:

- **Browserbase** — first choice. Pay-per-session, mature, designed for agent loops.
- **Hyperbrowser** — backup.

Routing: new Railway endpoint `POST /browser/session` returns a session URL + auth token. Client opens a headless connection. Same pattern as `/stt/session` for Deepgram. Master key stays server-side.

### Tools

- `web_search(query, n=10)` — Brave Search API (cheap, no scraping). Or fall back to Google's PSE.
- `web_fetch(url) -> markdown` — readability extraction in the worker.
- `browse(start_url, instructions) -> {final_state, screenshots}` — agentic browse via the hosted browser. Used for login-walled or JS-heavy sites.

### Done when

`"find 20 productivity YouTubers under 100k subs and put them in a CSV on my desktop"` works.

---

## §6. Phase 4 — Background "spawned" agents (1 week)

Goal: long-running tasks run without blocking the user. Same UX as Clicky's "spawn" but no second cursor sprite.

### Mechanic

- Voice command starts. Loop runs as before.
- When a turn estimates >2 min remaining (heuristic: `recall` returns >5 unfinished `task_*` entries, or model emits a planning tool-call with a multi-step list), the runtime *detaches*: a small task pill appears in the panel ("Running: Q2 invoice grab — turn 12") and the user can fire new voice commands.
- The detached agent runs in its own asyncio task with its own `session_id` row. Multiple can run concurrently.
- Notification when done (macOS UNUserNotificationCenter / Windows toast).

### What we explicitly don't copy from Clicky

- ❌ **Second cursor sprite.** No "clone" overlay. Just the existing panel with a list of running sessions.
- ❌ **Voice trigger word** ("clicky agent ..."). The runtime decides when to detach based on task shape.

### Done when

User says `"research and write a competitive analysis of the top 5 voice AI startups"`, sees a "Running" pill, immediately uses Uxie for a different command in parallel, and gets a notification 8 minutes later that the analysis is done with a path to the markdown file.

---

## §7. Phase 5 — Teaching mode (cursor drag, no fake sprite) (1 week)

Goal: "show me how to do X in this app" — the cursor moves to the right control while voice narrates. No overlay window with a fake cursor sprite.

### Protocol (reusing Clicky's idea)

LLM embeds tags in its response stream:

```
[POINT:label:appName]            # AX-resolved (preferred)
[POINT:x,y:label:screenN]        # vision-based fallback
```

### Renderer

1. Parse tags as they arrive in the SSE response.
2. Resolve coordinate:
   - `axui_resolve(appName, label)` → exact frame in screen coords (Mac AX / Windows UI Automation)
   - Fallback to vision-emitted `(x, y)`
3. **Drag the system cursor** along an ease-out-cubic bezier (~500ms) to the target.
   - Mac: `CGWarpMouseCursorPosition` (no Accessibility needed for visual move; switch to posted `mouseMoved` events if hover effects matter)
   - Windows: `SetCursorPos`
4. Drop a 28px pulsing ring marker at the destination, fades over 2s. One non-activating `NSPanel` (Mac) / topmost layered window (Win). No persistent overlay.
5. Speak the label via the existing TTS path.

### Critical UX rules

- **Abort on user input.** Tap into HID-source mouseMoved (not synthetic — `kCGEventSourceStateHIDSystemState`). If real user mouse delta during our drag, cancel mid-animation.
- **Only on explicit ask.** "Show me where..." / "How do I..." in the transcript flips a `teacher_mode=true` system-prompt addendum that allows the model to emit POINT tags. In normal answers, model is told never to emit them.
- **Settings toggle to disable entirely.** Some users will hate cursor hijacking.

### Why this is better than Clicky's approach

- No 800-line `OverlayWindow.swift` clone
- Exact targeting via AX (Clicky relies on the model eyeballing pixels — misses by 20-50px on small UI)
- Reversible the moment the user touches their mouse — Clicky keeps animating and fights the user

### Done when

`"how do I export this Figma frame as PNG?"` triggers cursor drag to File → Export → PNG with voice narration, and the user can override mid-flow.

---

## §8. Phase 6 — Long-term memory (3-4 days)

Goal: remember user preferences and prior session findings across launches.

### Stack

- **`sqlite-vec`** in the same SQLite file as the context bag. No new service.
- **Embeddings**: `text-embedding-3-small` via the existing OpenAI proxy on Railway.
- **What gets remembered**: explicit user preferences (e.g. "I always cc legal@ on contract emails") and *summaries* of completed sessions, not raw transcripts. Summarize at session end with a Haiku-cheap prompt and embed the summary.

### Tools

- `remember(fact, tags?)` — model calls this when it learns something stable about the user.
- `recall_long_term(query, limit=5)` — vector search over the embedded summaries + preferences.

### Privacy gate

`Settings → Memory → Export | Clear all`. Non-negotiable for trust. Memory is the feature most likely to spook users, and a clear "delete everything" button buys credibility.

### Done when

After completing a "research X then email a summary to Y" flow once, doing it again with a different X automatically uses the same email format and recipient style without being asked.

---

## §9. Multi-agent orchestration — when, not whether

The previous draft jumped straight to a router + 5 specialists. This is wrong for v1. Here's the precondition:

> **Don't split the agent until a single agent with 50 turns and the full tool registry is measurably failing on real user tasks because of (a) tool-list size confusing the model, or (b) parallel-execution opportunity wasted.**

If we hit (a), measured by tool selection accuracy <85% on a labeled eval set, *then* split into:
- **Router** (Haiku 4.5): JSON-only, picks specialist, drafts task brief
- **System** (Sonnet 4.6): apps, files, native integrations
- **Code** (Opus 4.6): writes/builds code in a workspace
- **Research** (Sonnet 4.6): web tools

If we hit (b), measured by sessions where two independent task branches sit serial when they could run parallel, add `asyncio.gather`-based fan-out within the system agent, *not* a full orchestrator layer.

The handoff schema (§3 in the prior draft) is right when we get there — task briefs in, task reports out, all writes go through the context bag. Just don't pre-build it.

---

## §10. Comparison: Uxie vs Clicky vs raw Anthropic computer-use

| | Clicky (now) | Anthropic computer-use | Uxie (after this plan) |
|---|---|---|---|
| Trigger | Push-to-talk + voice | API only | Push-to-talk + voice |
| Tool layer | `[POINT]` tags + new actuator tools (CGEvent + AppleScript) | `screenshot` + `click(x,y)` + `type` + `keypress` | Typed tool registry: native APIs first (EventKit, AppleScript, COM), synthetic input never |
| Coordinate accuracy | Vision only (~70%) | Vision only | AX/UIA-resolved with vision fallback (>95%) |
| Cross-platform | Mac only (Win in dev) | Cross-platform via screenshots | Mac + Win parity from day one |
| State persistence | Conversation in memory | Conversation in memory | SQLite context bag, survives crashes |
| Background tasks | "Spawn clone" with 2nd cursor | None | Detached sessions in panel pill, no sprite |
| Model | Claude Sonnet 4.6 | Claude only | Provider-agnostic via Railway proxy |
| Memory | None | None | sqlite-vec summaries with explicit user controls |

**The strategic difference**: Clicky leans on vision and synthetic input — flashy demos, brittle outcomes. Uxie leans on native APIs first (EventKit, AppleScript, COM, Accessibility) — boring under the hood, dramatically more reliable. We add cursor drag (Phase 5) for the rare "show me how" case where vision is the only path.

---

## §11. What stays untouched

Don't rewrite these — they work:

- Hotkey handler (Rust helper, both platforms)
- Deepgram STT pipeline
- Approval gate (just gets reused with new tool flags)
- Railway auth + proxy
- Existing connectors (Gmail, Slack, etc.) — they migrate into the new tool registry as-is

---

## §12. Sequencing

| Week | Phase | User-visible result |
|---|---|---|
| 1 | Phase 0 — turn cap + streaming + cancel | Long tasks complete; progress visible; cancellable |
| 2-3 | Phase 1 — cross-platform tool registry | Win + Mac feature parity for all tools |
| 4 | Phase 2 — context bag | Long sessions resume across crashes; agents stop re-doing work |
| 5 | Phase 3 — web research | Influencer-CSV-style demos work |
| 6 | Phase 4 — background agents | Multiple long tasks running in parallel |
| 7 | Phase 5 — teaching mode | "Show me how" with cursor drag |
| 8 | Phase 6 — long-term memory | Personalization improves over time |
| later | Multi-agent split | Only if Phase 0-6 evals demand it |

That's 7 weeks to ship through Phase 5. Phase 6 and multi-agent are post-launch optimizations.

---

## §13. The bugs that will eat your time

In rough order of expected pain:

1. **AppleScript silently no-ops** when target app isn't running. Wrap every call in a `tell application "Foo" to activate; delay 0.3` preflight; check `application "Foo" is running` first.
2. **xcodebuild invalidates TCC permissions** (Clicky's AGENTS.md warns about this). If we ever ship the Mac-app-builder, never invoke from a session that needs accessibility/screen recording afterward.
3. **CGEvent posted clicks miss when windows shift.** Don't ship synthetic clicks. Stick to AppleScript / EventKit / AX.
4. **COM HRESULTs are cryptic.** Pre-translate the common ones (Outlook not running, OneNote not signed in) into human strings before returning to the model.
5. **TCC reset on resigned binaries.** Already a known Uxie issue — `tccutil reset Microphone ai.smallest.uxie` is the recipe; document in the user-facing changelog when shipping a re-signed update.
6. **Tool selection drift** as the registry grows. Build an eval harness early (50 labeled voice prompts → expected tool sequence). Re-run on every system-prompt change.

---

## §14. Open decisions before week 1 ends

- [ ] Browserbase vs Hyperbrowser vs Playwright-bundled. Recommendation: Browserbase.
- [ ] Embedding model: `text-embedding-3-small` vs `-large`. Recommendation: small for v1.
- [ ] Working-directory location on Mac: `~/Library/Application Support/Uxie/agents/` (sandbox-friendly) vs `~/Uxie/agents/` (visible). Recommendation: the former.
- [ ] Long-term memory opt-in default: on or off. Recommendation: off until Phase 6 ships, then on with a clear notification.
- [ ] Approval scope for `shell_exec`: every call, or first-time-per-session-with-similar-prefix. Recommendation: every call in v1, refine after we see real usage.
