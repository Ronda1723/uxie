# Uxie iOS — Build Plan (handoff for a fresh agent)

> This document is self-contained. The receiving agent has not seen the prior conversation. Read the **Repo orientation** section first, then **Architecture decision**, then the phased plan.

---

## What Uxie is

Uxie is a voice-powered desktop agent. The user holds a hotkey, speaks, and the app either dictates into the focused app or runs an agentic command (send email, post Slack, open app, etc.). Today it ships on **macOS** and **Windows** as an Electron app. We want to add **iOS**.

The desktop product won the user with one mechanic: *push key → talk → done*. iOS doesn't have global hotkeys, doesn't allow arbitrary cross-app control, and runs a fundamentally different sandbox. So the iOS port is **not a recompile** — it's a re-imagining of the same product with the desktop's compute moved to the cloud.

---

## Repo orientation (read these files first, in order)

The Mac/Windows source lives at `uxie-app/uxie` (private). Local working copy: `/Users/rounaklenka/MiniFlow`.

1. `CLAUDE.md` — top-level architecture and the "all API calls go through Railway" rule. Non-negotiable.
2. `miniflow-engine/audio.py` — STT pipeline (Deepgram WebSocket, ephemeral key minted by Railway). The auth pattern here is what iOS reuses.
3. `miniflow-engine/agent.py` — the agent loop (`execute_command`, max 4 turns, tool-calling). This is the reference implementation; on iOS the loop moves to the server.
4. `miniflow-engine/llm.py` — provider abstraction. Default provider is `"uxie"` which routes to Railway `/llm/chat` and `/llm/stream`.
5. `miniflow-engine/connectors/` — Gmail, Slack, Notion, Linear, GitHub, Calendar, Spotify connectors. Each exports a `TOOLS` schema list and an `execute()` function.
6. `uxie-backend/proxy.py` — the Railway service. `/llm/chat`, `/llm/stream`, `/stt/session`. iOS will call the same endpoints + a new one we'll add.
7. `uxie-backend/auth.py` — email-OTP → JWT (RS256). iOS reuses verbatim.

Don't read the Electron renderer code (`miniflow-electron/src/renderer/`) — UI is being redesigned for iOS from scratch (SwiftUI), and the existing React component shapes won't translate.

---

## Architecture decision: move the agent loop server-side

Today the agent loop runs **inside the user's machine** (Python engine bundled in the Electron app). iOS can't ship a local Python interpreter + FastAPI server practically — app size, background limits, sandbox.

**Decision**: introduce a new Railway endpoint `POST /agent/execute` that runs the entire tool-calling loop server-side and streams progress back via SSE. iOS becomes a thin client.

**Why this is the right call** (and we should eventually port Mac/Windows to it too):

- iOS gets feature parity for free with everything the server already does (Gmail, Slack, etc.)
- No client-side LLM key handling drift between platforms
- Tool registry maintained in one place
- Cross-device history (start a command on iOS, see it on Mac) is automatic

**What stays client-side on iOS**:
- Microphone capture → ephemeral Deepgram WS (same handshake as desktop)
- Approval UI (server pauses the loop, asks client, client shows a sheet, user approves, loop resumes)
- iOS-native tool execution (Shortcuts, share sheet) when the LLM picks an iOS-only tool

**What moves server-side**:
- The 4-turn loop (currently `agent.py:798-830`)
- All OAuth-connector tool execution
- All LLM calls (already there)
- Approval gate (becomes a server-side `asyncio.Event` keyed by session ID, resolved by an HTTP callback from the client)

---

## What's gone on iOS (and what replaces it)

| Desktop capability | iOS reality | Replacement |
|---|---|---|
| Global `fn`/Right-Alt hotkey | iOS has no system-wide hooks | Push-to-talk button in-app + Action Button binding (iPhone 15 Pro+) + Apple Watch crown |
| `open -a "Notion"` to launch any app | Sandbox forbids it | URL scheme tools (`notion://`, `slack://`) when the LLM knows them; otherwise no-op |
| `osascript -e 'quit app "X"'` | Forbidden | Drop tool entirely on iOS |
| `CGEventPost` typing into focused app | Forbidden | Result shown in Uxie, with "Copy" / "Share Sheet" / "Send" affordances |
| `AXUIElementCopyAttributeValue` (read selection from another app) | Forbidden | Share Extension: user shares text *into* Uxie, then runs a command on it |
| Local file create/move (`shutil`) | Sandboxed to Documents folder | iCloud Drive / Files-app picker; not in v1 |
| MCP servers (local subprocesses) | Forbidden | Drop in v1; revisit if Apple ever opens this |

iOS gains:
- **Action Button** (iPhone 15 Pro+) → push-to-talk in one press, no app-switch
- **Lock Screen Live Activity** showing "Listening… / Processing…"
- **Siri Shortcuts** via `AppIntents` — "Hey Siri, ask Uxie to summarize my unread Slack"
- **Share Sheet extension** — share any text into Uxie to run a command on it
- **Apple Watch companion** — push-to-talk from the wrist (this could be the killer demo)

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| App | SwiftUI, iOS 17+ | iOS 17 unlocks `AppIntents`, modern `AVAudioEngine` async APIs, observable framework. Don't drag Combine + UIKit unless forced. |
| Audio capture | `AVAudioEngine` + `AVAudioConverter` to 16kHz PCM | Same format Deepgram expects. Mirrors what the desktop renderer does in Web Audio. |
| Networking | `URLSession.bytes(for:)` for SSE; `URLSessionWebSocketTask` for Deepgram | Native, no third-party. |
| Auth & token storage | Keychain (`kSecClassGenericPassword`) | Drop-in better than the desktop's plaintext `~/miniflow/uxie_auth.json` |
| OAuth flow | `ASWebAuthenticationSession` | Apple's blessed in-app browser; survives App Review |
| Push-to-talk | `AVAudioSession.Category.playAndRecord` + background mode `audio` + the **Push-to-Talk Framework** (`PushToTalk` framework, iOS 16+) for the Action Button bind | The PTT framework is the only sanctioned way to do voice-while-locked. Worth understanding early. |
| Live Activity | `ActivityKit` | Listening/processing indicator on Lock Screen + Dynamic Island |
| Shortcuts integration | `AppIntents` framework | Lets Siri call into Uxie; lets users wire Shortcuts to Uxie commands |

---

## Phased plan

### Phase 0 — Backend prep (week 1, server-side only, zero iOS code)

This is unblocking work. Goal: the existing desktop app continues working, but a new server-side path exists that iOS will use.

1. **New endpoint** `POST /agent/execute` on Railway (`uxie-backend/agent.py` — new file).
   - Body: `{transcript, conversation_id, tools_available_on_client: [...]}`
   - Returns: SSE stream with events `tool_call_start`, `tool_call_result`, `approval_needed`, `approval_response_required`, `final_text`, `done`
   - Internally runs the same 4-turn tool-calling loop as `miniflow-engine/agent.py:798-830` but server-side, calling Groq/OpenAI directly with the server-side keys.

2. **Connector tools move server-side.** Today they live in `miniflow-engine/connectors/`. Copy them to `uxie-backend/connectors/` and adapt: `oauth.get_token(provider)` becomes `db.get_oauth_token(user_id, provider)`. Same OpenAI tool schemas.

3. **Approval bridge.** When the loop hits a destructive tool, server emits `approval_needed` and parks a coroutine on `asyncio.Event`. Client POSTs `/agent/approve/{session_id}` with `{approved: bool}` to resume.

4. **Tool partition.** Server tools = connectors. Client-only tools = `open_url`, `share_sheet`, `copy_to_clipboard`, etc. The request payload tells the server "here are the tools the client can run"; server merges them into the tool list it sends to the LLM, but when the LLM picks a client-only tool, server forwards `tool_call_start` to the client and waits for a result.

5. **Test from desktop first.** Add a feature flag in the Mac app to route through `/agent/execute` instead of running the loop locally. If parity holds for one week, the iOS port is unblocked.

### Phase 1 — iOS scaffolding (week 2)

1. **New repo**: `uxie-app/uxie-ios` (separate from `uxie-app/uxie` — Xcode workspaces don't mix well with mixed-language repos).
2. SwiftUI app target, iOS 17 minimum, iPhone-only (iPad later).
3. Onboarding: email → OTP → JWT. Store in Keychain. Reuse `/auth/send-otp` and `/auth/verify-otp` endpoints unchanged.
4. Tab structure: **Home** (push-to-talk), **History**, **Connectors**, **Settings**. Match the desktop product's mental model.
5. Lock the design system early: cream/tan/terracotta palette already chosen on desktop (`miniflow-electron/src/renderer/styles.css` has the tokens — port them to a SwiftUI `Color` extension).

### Phase 2 — Mic + STT (week 3)

1. `AVAudioSession` setup with `playAndRecord`, `defaultToSpeaker`, `allowBluetooth`.
2. `AVAudioEngine` tap that converts to 16kHz Int16 PCM frames.
3. Mint ephemeral Deepgram key from `POST /stt/session` (existing endpoint).
4. Open `URLSessionWebSocketTask` to `wss://api.deepgram.com/v1/listen?...` with `Authorization: Token <ephemeral>` header (note: **Token**, not Bearer — Deepgram is fussy about this).
5. Stream PCM frames, listen for partials, surface interim text in UI, dispatch final on button-release.
6. Test thoroughly with bluetooth headsets, AirPods, mute switch, phone calls, Siri interruptions. The audio session interruption matrix on iOS is the bug factory — budget half a week.

### Phase 3 — Agent integration (week 4)

1. After dictation/command STT returns text, decide mode same way desktop does (push-to-talk = dictation; long-press = command). For v1, default to command mode for everything; dictation only matters when typing into another app, which iOS can't do.
2. POST text to `/agent/execute` with `tools_available_on_client: ["open_url", "share_sheet", "copy_to_clipboard", "create_calendar_event_local"]`.
3. Parse SSE stream. For each event:
   - `tool_call_start` → show "Doing X…" in a Live Activity
   - `approval_needed` → present a sheet with the action summary + Approve/Cancel
   - `final_text` → show in main view
4. Render history as you go.

### Phase 4 — iOS-native tools (week 5)

These are the tools that *must* be implemented on the client because they touch iOS:
- `open_url(url)` — `UIApplication.shared.open(url)`. Use this for `notion://`, `slack://`, `tel:`, `mailto:` etc.
- `share_sheet(text)` — `UIActivityViewController`
- `copy_to_clipboard(text)` — `UIPasteboard.general`
- `create_calendar_event_local(...)` — `EKEventStore` (asks for Calendar permission on first use)
- `add_reminder(...)` — `EKEventStore` reminders

Each needs to be implemented on the client AND advertised to the server in the `tools_available_on_client` payload.

### Phase 5 — iOS niceties (week 6)

In rough order of demo value:

1. **Action Button binding** (iPhone 15 Pro / 16 / Pro+): app provides a Shortcut intent "Talk to Uxie" → user binds Action Button to it in iOS Settings. Tap = push-to-talk.
2. **Live Activity + Dynamic Island**: shows "Listening…" / "Processing…" / final result. ~2 days of `ActivityKit` work.
3. **Apple Watch companion**: standalone watchOS target. Crown press or button → mic on → streams to phone via WatchConnectivity → phone does the rest. This is the differentiated demo.
4. **Share Extension**: user shares text from Safari/Mail/anywhere → Uxie pre-fills with "Selected text: ..." → user voices the command. Reproduces the desktop's selected-text feature.
5. **AppIntents donations** so Shortcuts and Siri can invoke Uxie commands.

### Phase 6 — TestFlight + App Store (week 7-8)

App Review will scrutinize:
- The microphone usage description (`NSMicrophoneUsageDescription`)
- The privacy nutrition label — be honest: "audio recordings sent to our servers and Deepgram for transcription, retained 30 days"
- The push-to-talk framework usage (only if you adopted it)
- Background mode `audio` (only if you actually keep mic on in background)

Review tip: ship without background-audio in v1. Foreground-only push-to-talk is far easier to defend.

---

## Things to *not* do in v1

- ❌ Don't ship a custom keyboard extension. Apple's keyboard extensions are awful (sandboxed without network by default, terrible memory limits). Save for v2 or never.
- ❌ Don't try wake-word ("Hey Uxie") — battery cost is enormous, Speech framework continuous-listening is unreliable, Apple won't approve it without strong justification.
- ❌ Don't ship a local LLM via Core ML — adds 1.5GB to app size, no quality match for GPT-4o, breaks the "all calls through Railway" architecture rule.
- ❌ Don't try to read other apps' text via accessibility — iOS Accessibility API is for *exposing* your app's content to assistive tech, not consuming others'. Different beast from macOS.

---

## Open decisions to make before week 1 ends

1. **Apple Developer enrollment**: $99/yr individual, or $99/yr organization once incorporated. App Store Connect setup. — **Blocker for TestFlight.**
2. **Bundle ID**: `ai.smallest.uxie` matches the Mac app. iOS reuses it (different platform, same identifier is fine).
3. **Privacy policy URL**: required by App Review. Spin up `uxie.ai/privacy` first.
4. **TestFlight tester list**: 25 internal slots, 10k external slots. Plan who tests.

---

## Quick reference: existing endpoints iOS will hit

| Endpoint | Purpose | Auth |
|---|---|---|
| `POST /auth/send-otp` | Email → 6-digit code | None |
| `POST /auth/verify-otp` | Code → JWT | None |
| `POST /stt/session` | Mint ephemeral Deepgram key | JWT |
| `POST /llm/chat` | Tool-calling LLM proxy | JWT |
| `POST /llm/stream` | SSE LLM proxy | JWT |
| `GET /user/status` | Tier, usage, referral stats | JWT |
| `POST /agent/execute` | **NEW (Phase 0)**: server-side agent loop with SSE | JWT |
| `POST /agent/approve/{session_id}` | **NEW (Phase 0)**: resolve approval gate | JWT |

---

## What success looks like (definition of done for v1)

A user installs Uxie from TestFlight, signs in with email+OTP, taps the on-screen mic button, says *"send John a Slack saying I'll be 10 min late"*, sees the approval sheet, taps **Send**, and gets a confirmation. End-to-end ≤ 8 seconds. No keyboard typing required. That's the bar.

Apple Watch demo: same thing from the wrist, no phone interaction. That's the wow.
