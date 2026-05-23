# Uxie — Project State (last updated 2026-05-24)

Single page summary of where Uxie stands. Read this before resuming work
after a break — it's faster than scrolling through commits.

## What ships solidly

### Voice surface
- Hotkey dictation (`fn` on Mac, Right-Alt on Windows) with grammar
  cleanup via Groq llama-3.3 / OpenAI gpt-4o
- Hotkey command mode → agent tool-calling (Gmail, Calendar, Drive, browser)
- **Text-selection transforms** — select text in any app, hold `fn`, say
  *"polish this"* / *"make this concise"* / *"translate to Spanish"* —
  the selection is replaced with the transformed text via clipboard +
  osascript Cmd+V. Triggered by keyword match in
  [agent.py::TRANSFORM_KEYWORDS](miniflow-engine/agent.py#L112).
- **Smart formatting** — bundle-id based context map. Mail.app gets
  email-shape output; Notes.app gets markdown; everything else gets
  prose. See [agent.py::APP_CONTEXT_MAP](miniflow-engine/agent.py#L616).

### Meeting recording (Granola-class)
- **System-audio + mic capture** via Swift `UxieAudioTap.app` sub-bundle
  ([native-helper/audio-tap/](native-helper/audio-tap/)). Uses
  AVCaptureSession (mic) + ScreenCaptureKit (system audio) — verified
  ~16 kHz mono int16 PCM at real-time rate.
- **Long-form Deepgram** streaming with `nova-3 + diarize + smart_format`.
  Finalized utterances appended live to SQLite at `~/miniflow/meetings.db`.
- **Calendar polling** every 60s detects upcoming events (Gmail OAuth
  with `calendar.readonly` scope). T-60s notification with Record / Skip
  action buttons.
- **Auto-detection** of Slack huddles, Zoom, Teams, Webex, Meet via the
  same Swift binary in `--watch` mode polling `SCShareableContent` every
  5s with state-change-only logging.
- **Structure-this-meeting** button → Railway `/llm/structure-meeting`
  with per-hour + per-day burst limits → Granola-style markdown summary.

### Background tasks (v1.1.0)
- **`Tasks` tab** in left rail. Type a prompt, agent runs on Railway
  detached from the HTTP request. Polling-based UI (2s while running).
- Read-only tools: gmail_search/read, calendar_list_events/check_avail,
  drive_search/read. Send / create / destructive tools NOT yet exposed
  to background tasks — waiting on the approval-gate flow.
- `tool_choice: "required"` on turn 0 so GPT-4o can't refuse with
  "I can't check your calendar".
- 401/403 errors get translated into "disconnect + reconnect in
  Settings → Connectors" before the LLM sees them.

### Backend (Railway)
- FastAPI on `uxie-production.up.railway.app`. Auth = email OTP via
  Resend → JWT (RS256, 30-day) → stored in macOS Keychain.
- Routes through Railway: `/llm/chat`, `/llm/stream`, `/llm/structure-meeting`,
  `/stt/session`, `/tasks/*`, `/oauth/google/*`, `/user/connections`,
  `/user/connector_token/{provider}`, `/agent/execute` (iOS-shaped).
- Per-month usage counters + per-hour/day burst limiter (`limits.py::check_burst`).
- Connector registry with Gmail + Calendar + Drive + Slack tool schemas.

### Release pipeline
- GitHub Actions: deep-signs every nested Mach-O inside-out, notarizes
  via App Store Connect API key, staples, generates `latest-mac.yml` +
  `latest.yml`, publishes Mac DMG + ZIP + Win EXE to `uxie-app/uxie-releases`.
- Tag-push triggers auto-publish (`git tag vX.Y.Z && git push --tags`).
- Auto-updater (electron-updater) works end-to-end on Mac.

## Known issues / rough edges

- **Bundle id is legacy.** `ai.smallest.uxie` — should rename to
  `ai.uxie.app` eventually, but it forces a one-time reinstall. Deferred.
- **No Sentry / error reporting.** When something breaks for a test user,
  we have no visibility. Highest-leverage operational TODO.
- **OAuth verification still in Testing mode.** Cap is 100 users. Each
  must be added to Google Cloud Console → OAuth consent screen → Test
  Users. Submitting for verification needs domain + privacy policy +
  demo video first.
- **No domain / no landing page / no ToS.** Deferred until ready for
  public launch.
- **No billing.** Pro tier exists in DB but no Stripe integration. All
  users are effectively on the 30-day trial extended indefinitely.
- **TCC dance for Screen Recording perm.** First Auto-detect toggle
  shows an in-app explainer, but the macOS quirk of requiring an app
  restart after granting is unavoidable.
- **Pre-existing TS error** at [audio.ts](miniflow-electron/src/renderer/audio.ts#L161)
  unrelated to anything new — silent type narrowing fix.

## Deferred (intentionally, with rationale)

- **Phase B**: Boss + worker decomposition for background tasks,
  scheduled/recurring tasks, Morning Brief flagship template, Slack
  OAuth wiring for the brief. *In flight as of 2026-05-24.*
- **Phase D**: Referral system (+30 day Pro reward), workflow template
  gallery, auto-stop meeting recording when call window closes.
- **iOS companion app**: separate repo at `uxie-app/uxie-ios`, paused.
- **Local LLM option**: Mac M-series can run Whisper/Llama locally but
  the addressable market is small. Wait for paying-customer ask.
- **Plugin marketplace**: premature — too few users.
- **Team/workspace features**: single-player retention first.
- **Personal memory / knowledge graph**: the highest-compounding long-term
  feature, but blocked on getting daily-active users first.

## The four files that matter if reviving

If you sit down 3 months from now and have to remember how things work:

| File | What lives there |
|---|---|
| [miniflow-engine/agent.py](miniflow-engine/agent.py) | Hotkey command path. Tool registry. Transform + formatting. System prompts. |
| [miniflow-engine/audio_meeting.py](miniflow-engine/audio_meeting.py) | Meeting recording — spawns Swift tap, pipes PCM to Deepgram, appends transcripts. |
| [miniflow-engine/meeting_watcher.py](miniflow-engine/meeting_watcher.py) | Auto-detection — spawns Swift tap in `--watch` mode, parses JSON window events. |
| [native-helper/audio-tap/Sources/UxieAudioTap/main.swift](native-helper/audio-tap/Sources/UxieAudioTap/main.swift) | Single Swift binary with two modes: audio capture (default) and window watcher (`--watch`). |
| [uxie-backend/tasks.py](uxie-backend/tasks.py) | Background-task agent loop on Railway. |
| [uxie-backend/connectors/google.py](uxie-backend/connectors/google.py) | Gmail + Calendar + Drive tools as HTTP calls with 401-refresh-retry. |

## Where to start adding new features

- A new agent tool → add a schema entry in
  [uxie-backend/connectors/{provider}.py](uxie-backend/connectors/),
  branch in its `execute()`, done. The Mac agent and Tasks tab both
  pick it up automatically via the registry.
- A new tab in the Mac UI → mirror `MeetingsTab.tsx` / `TasksTab.tsx`
  shape, add to the `SidebarTab` union in `App.tsx`, add a `Sidebar.tsx`
  nav row.
- A new IPC channel → `preload.ts` exposes it, `ipc.ts` registers a
  handler that proxies to the engine via `invoke()`.

## When in doubt

Read [PROCESS.md](PROCESS.md). It has the change-and-release lanes
(Quick / Standard / Full / Release / Hotfix) and the project-specific
landmines that have bitten us. Skipping lanes is how we ship the next
React-hook bug.
