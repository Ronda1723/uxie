# Execution Plan — Uxie next 60 days

Ties together [IOS_PLAN.md](./IOS_PLAN.md) and [AGENT_PLAN.md](./AGENT_PLAN.md) into a single ordered checklist. The two plans share infrastructure: iOS Phase 0 needs a server-side agent loop; agent system Phase 1 needs cross-platform tool registry. So they have to be sequenced carefully or we'll do double work.

**Single principle**: don't start iOS until the agent loop is provably stable on desktop. Otherwise we'll port a moving target.

---

## Sequencing logic

```
┌──────────────────────────────────────────────────────────────────┐
│ Days 1-7   Agent Phase 0 (loop + streaming + cancel)            │
│            ─ unblocks everything else                            │
├──────────────────────────────────────────────────────────────────┤
│ Days 8-21  Agent Phase 1 (cross-platform tool registry)         │
│            ─ Mac + Win parity locked in                          │
├──────────────────────────────────────────────────────────────────┤
│ Days 22-28 Agent Phase 2 (context bag)                          │
│            ─ + parallel start: iOS Phase 0 (server-side loop)    │
├──────────────────────────────────────────────────────────────────┤
│ Days 29-35 Agent Phase 3 (web research)                         │
│            + iOS Phase 1 (Swift scaffold, login)                 │
├──────────────────────────────────────────────────────────────────┤
│ Days 36-49 Agent Phase 4 (background sessions)                  │
│            + iOS Phase 2 (mic + Deepgram)                        │
│            + iOS Phase 3 (agent integration)                     │
├──────────────────────────────────────────────────────────────────┤
│ Days 50-60 iOS Phase 4-5 + Agent Phase 5 (cursor teaching)      │
└──────────────────────────────────────────────────────────────────┘
```

Memory (Agent Phase 6) and Multi-agent split are **post-launch**, not in this window.

---

## Days 1-7 — Agent Phase 0 foundations

The cheapest, highest-leverage week. Today the agent loop has `MAX_TURNS = 4` and is silent until done. Fix both, ship.

- [ ] Bump `MAX_TURNS` from 4 to 50 in [agent.py:798-830](miniflow-engine/agent.py#L798-L830)
- [ ] Add per-turn timeout (30s) and total session budget (5min)
- [ ] Emit `agent-progress` event each turn with `{turn, thinking, tool_call}`
- [ ] Renderer: show latest progress line in the existing Home panel (no new UI)
- [ ] Cancel button: holding `fn` again sets a session-level `asyncio.Event` checked before each turn
- [ ] Persist session state to `~/miniflow/agent_sessions/<session_id>.json` per turn
- [ ] Acceptance test: `"summarize every PDF in my Downloads folder and email me the summary"` runs across multiple turns with visible progress, can be cancelled, resumes if app crashes
- [ ] Ship as v1.0.19 (Mac + Win)

**Decision points this week:**
- [ ] Pick browser provider for Phase 3 — Browserbase vs Hyperbrowser. Sign up for whichever's cheaper.
- [ ] Decide whether dictation mode also needs the new turn cap (probably no — it's single-call grammar correction)

---

## Days 8-21 — Agent Phase 1: cross-platform tool registry

Two-week chunk. Most of the work is Windows impls, since Mac mostly already has these via `_execute_local`.

### Tool protocol refactor (days 8-10)
- [ ] Define `Tool` protocol (name, schema, platforms, requires_approval, async execute)
- [ ] Define `ToolResult` (success/failure/not_supported/needs_confirmation, structured fields)
- [ ] Refactor existing `_execute_local` callsites to use the new protocol — Mac stays working
- [ ] Add `not_supported` as first-class result the LLM sees and can route around

### Mac tool ports (days 11-14)
- [ ] `create_reminder` (EventKit) + `create_calendar_event` (EventKit)
- [ ] `create_note` (AppleScript → Notes.app)
- [ ] `applescript(source)` generic escape hatch
- [ ] Sandboxed working directory: `~/Library/Application Support/Uxie/agents/<session_id>/`
- [ ] `read_file` / `write_file` / `list_dir` (sandbox-aware, approval gate when outside working dir)
- [ ] `shell_exec(cmd, cwd, timeout)` (always behind approval gate)

### Windows tool impls (days 15-19)
- [ ] `open_application` via `start ""` shell + UWP app fallback
- [ ] `open_url` via `start <url>`
- [ ] `read_file` / `write_file` / `list_dir` (same Python stdlib, different sandbox path)
- [ ] `shell_exec` via subprocess
- [ ] `create_reminder` / `create_calendar_event` — Microsoft Graph if signed in, else `not_supported` with clear message
- [ ] `create_note` — `.txt` in `~/Documents/Uxie Notes` (skip OneNote COM for v1)
- [ ] `powershell(source)` escape hatch
- [ ] `clipboard_read` / `write` (pyperclip already cross-platform)

### Acceptance + ship (days 20-21)
- [ ] Eval set: 30 voice prompts × 2 platforms = 60 expected outcomes. Pass rate >85%.
- [ ] `"open Spotify and play Bicep's Glue"` works on both platforms
- [ ] `"create a reminder for tomorrow 9am to call my mom"` works on Mac (Win returns clear `not_supported`-with-suggestion if not signed into Graph)
- [ ] Ship v1.0.20

**Decision points:**
- [ ] Microsoft Graph onboarding flow on Windows — ship in v1.0.20 or push to v1.0.21? (Recommend: push, ship Phase 1 without it.)

---

## Days 22-28 — Agent Phase 2 + iOS Phase 0 in parallel

This is when iOS work actually begins. Two parallel tracks.

### Agent track: context bag
- [ ] SQLite schema (`session`, `context_entries`) at `~/miniflow/agent.db`
- [ ] Context-write hooks in every tool's `execute()`
- [ ] `recall(types?, tags?, since_seconds?, limit=10)` tool added to registry
- [ ] System prompt updated to tell model the bag exists + when to call `recall`
- [ ] Acceptance: 30+ tool-call session survives app restart, doesn't redo finished steps
- [ ] Ship v1.0.21

### iOS track (parallel — separate agent if delegated)
- [ ] Backend prep: new endpoint `POST /agent/execute` on Railway with SSE
- [ ] Backend: connector tools migrate to `uxie-backend/connectors/` (Gmail send, Slack post, Calendar)
- [ ] Backend: server-side approval gate via `asyncio.Event` keyed by session_id
- [ ] Backend: `POST /agent/approve/<session_id>` to resolve
- [ ] Feature flag in Mac client to route through `/agent/execute` instead of local loop
- [ ] Run Mac client through new server-side path for one full week as parity check

**Decision points:**
- [ ] Apple Developer enrollment — start now (takes 1-3 days for individual, longer for organization). **Hard blocker for TestFlight.** Don't skip.
- [ ] iOS repo: separate `uxie-app/uxie-ios` or subfolder of existing repo? Recommend separate.

---

## Days 29-35 — Agent Phase 3 + iOS scaffold

### Agent track: web research
- [ ] Browserbase (or chosen provider) account + API key in Railway env
- [ ] New endpoint `POST /browser/session` mints ephemeral session token
- [ ] `web_search(query)` tool — Brave Search API
- [ ] `web_fetch(url) -> markdown` tool — readability extraction in Railway worker
- [ ] `browse(url, instructions)` tool — agentic browse via hosted browser
- [ ] Acceptance: `"find 20 productivity YouTubers under 100k subs and put them in a CSV on my desktop"` works
- [ ] Ship v1.0.22

### iOS track: scaffold
- [ ] New Xcode project in `uxie-app/uxie-ios`, SwiftUI, iOS 17+, iPhone-only
- [ ] Bundle ID `ai.smallest.uxie` (matches Mac)
- [ ] Onboarding: email → OTP → JWT (reuses existing `/auth/send-otp`, `/auth/verify-otp`)
- [ ] JWT in Keychain via `kSecClassGenericPassword`
- [ ] Tab structure: Home / History / Connectors / Settings
- [ ] Color tokens ported from desktop `styles.css` to a SwiftUI `Color` extension
- [ ] Submit privacy policy at `uxie.ai/privacy` (App Review requirement)

---

## Days 36-49 — Agent Phase 4 + iOS Phase 2-3

### Agent track: background sessions
- [ ] Detached agent runner (separate asyncio task per session)
- [ ] "Running" pill in panel listing active sessions
- [ ] `UNUserNotificationCenter` (Mac) / Windows toast on completion
- [ ] Acceptance: two long tasks running concurrently, user uses Uxie for unrelated commands in parallel
- [ ] Ship v1.0.23

### iOS track: mic + agent integration
- [ ] `AVAudioSession` setup (`playAndRecord`, `defaultToSpeaker`, `allowBluetooth`)
- [ ] `AVAudioEngine` tap → 16kHz Int16 PCM frames
- [ ] Mint ephemeral Deepgram key from `/stt/session`
- [ ] `URLSessionWebSocketTask` to Deepgram with `Authorization: Token <key>` (Token, not Bearer — Deepgram is fussy)
- [ ] Test interruption matrix: bluetooth headset connect/disconnect, mute switch, Siri interrupt, phone call interrupt — budget 2 days for this alone
- [ ] Push-to-talk button (large, on-screen) → mic open → text → POST to `/agent/execute`
- [ ] Parse SSE stream: `tool_call_start` → status update; `approval_needed` → sheet; `final_text` → main view

---

## Days 50-60 — iOS niceties + Agent teaching mode

### iOS track: native niceties
- [ ] Action Button binding (iPhone 15 Pro+) via `AppIntents` Shortcut "Talk to Uxie"
- [ ] Live Activity + Dynamic Island: "Listening… / Processing… / done"
- [ ] iOS-native tools wired to client: `open_url`, `share_sheet`, `copy_to_clipboard`, `create_calendar_event_local` (EventKit)
- [ ] Each registered with server in `tools_available_on_client` payload
- [ ] Internal TestFlight (25 testers)

### Agent track: teaching mode
- [ ] System prompt addendum: model emits `[POINT:label:appName]` only when transcript matches "show me / how do I"
- [ ] Tag parser in SSE response stream
- [ ] AX resolver (Mac `AXUIElement`) → exact frame in screen coords
- [ ] Cursor drag via `CGWarpMouseCursorPosition` along ease-out-cubic bezier
- [ ] 28px pulsing ring marker at destination, fades 2s
- [ ] HID-source mouse-delta listener → cancel drag if user moves real mouse
- [ ] Settings toggle: enable/disable teaching mode (default on)
- [ ] Windows port: `SetCursorPos` + UI Automation
- [ ] Ship v1.0.24

---

## What's deliberately NOT in this 60 days

- ❌ Long-term memory (sqlite-vec) — Phase 6, post-launch
- ❌ Multi-agent split — only if evals demand it later
- ❌ Apple Watch companion — biggest demo risk, defer to v2
- ❌ macOS notarization — needs Apple Dev org account, currently signed but unnotarized
- ❌ Authenticode signing for Windows — $300-500/yr cert, post-launch
- ❌ Apple App Store submission — TestFlight only at day 60
- ❌ iPad version — iPhone first
- ❌ Web app, browser extension, anything that isn't desktop-or-iPhone

---

## Critical-path blockers to start today

These have lead times. Start them now even if you can't act on the result yet.

- [ ] **Apple Developer enrollment** — needed by day 50 for TestFlight, takes 1-7 days
- [ ] **Browserbase / Hyperbrowser account** — needed by day 29
- [ ] **Microsoft Graph app registration** — needed by day 22 if Win Calendar is in scope
- [ ] **Privacy policy at `uxie.ai/privacy`** — needed by day 28 (App Review)
- [ ] **Brave Search API key** — needed by day 29

---

## Health checks every Friday

Run these each week. If any fail, stop and fix before adding new work.

- [ ] Mac DMG and Win EXE both build green on CI for the latest commit
- [ ] Latest installed version answers `"what time is it"` in <3s on both OSes
- [ ] Auth still works (email → OTP → JWT round trip)
- [ ] Eval set pass rate ≥ 85% on both Mac and Win
- [ ] Railway backend responding (curl `/user/status` with a known JWT)

---

## How to use this doc

Check things off as they ship. When a phase is done, update the version number you shipped to (the v1.0.19/.20/.21/.22/.23/.24 cadence above). When a decision point lands, write the decision under the bullet so future-you knows why.

If something slips, push everything after it back proportionally. Don't try to compress later phases to "make up time" — that's how you ship something half-finished.

When in doubt: **ship Mac + Win parity before iOS. iOS without a stable backend is a doomed port.**
