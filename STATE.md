# Uxie — Project State (last updated 2026-05-24, v1.4.0 final)

Single page summary of where Uxie stands as the project closed out for
private beta. Read this before resuming work after a break.

## Scope status — what shipped vs what didn't

**Shipped (production-ready for ≤100 testers via Google OAuth Testing mode):**

| Capability | Where | Notes |
|---|---|---|
| Voice dictation + grammar cleanup | engine | fn / Right-Alt hotkey, Groq Llama-3.3 grammar pass |
| Voice agent commands (Gmail / Calendar / Drive / Slack) | engine + Railway | tool-calling via OpenAI gpt-4o |
| Text-selection transforms (polish / concise / tone / translate) | engine | reads AX selected text, pastes back via clipboard + Cmd+V |
| App-specific smart formatting (Mail → email, Notes → markdown) | engine | bundle-id → context map |
| Meeting recording — mic + system audio | Swift sub-bundle | AVCaptureSession + ScreenCaptureKit, real-time 16 kHz mono mix |
| Long-form Deepgram transcription with diarization | engine | nova-3 + speaker labels |
| Calendar polling → notification → record/skip | engine + Mac main | 60s poll loop, native macOS notifications |
| Auto-detection of Slack / Zoom / Teams / Meet / Webex windows | Swift `--watch` mode | `SCShareableContent` poll every 5s, state-change-only logging |
| Auto-stop recording on call window close | engine | `meeting_watcher._on_disappeared` |
| Structure-this-meeting (Granola-style summary) | Railway | `/llm/structure-meeting` with per-hour + per-day burst limits |
| Background agent tasks ("Tasks" tab) | Railway + Mac | detached agent loop, polling UI, JWT-gated |
| Approval gate for destructive tools | Railway + Mac | `/tasks/{id}/approve` parks the loop on asyncio.Event; inline approval card in Tasks tab |
| Parallel tool calls | Railway | `asyncio.gather` over all `tool_calls` in a turn |
| Scheduled / recurring workflows ("Briefings" tab) | Railway cron + Mac | TEMPLATE_REGISTRY with three baked-in templates |
| **Morning Brief**, **End-of-Day Recap**, **Weekly Digest** | Railway | parallel Gmail + Calendar (+Slack) workers → GPT-4o synthesis → email via Resend + notification |
| Referral system (link, share, redeem, +30-day Pro reward) | Railway + Mac Settings → Invite tab | |
| Slack OAuth flow | Railway | parallels Google OAuth; needs `SLACK_CLIENT_ID` + `SLACK_CLIENT_SECRET` env vars |
| Sentry error reporting | engine + renderer + backend | 3 separate projects under one org |
| Privacy policy + ToS | repo root (PRIVACY.md, TERMS.md) | markdown; not hosted publicly yet |
| Auto-update flow | electron-updater | Mac DMG notarized + stapled; Windows EXE built but Authenticode-unsigned |

**Deferred — picked up if we ever revive the project:**

| Item | Why deferred | Effort to add |
|---|---|---|
| Boss + worker decomposition (real multi-agent) | Parallel tool calls cover 80% of the win | 3-4 days |
| iOS companion app | repo at `uxie-app/uxie-ios`, paused | 2 weeks for parity |
| Vector memory across meetings + dictations | needs daily-active users first | 1 week |
| Local LLM option | small addressable market | 3 days |
| Plugin marketplace | premature | open-ended |
| Public Google OAuth verification | needs domain + landing page + demo video | 4-6 weeks elapsed (Google review) |
| Stripe billing | Pro tier is hypothetical until paying customers ask | 3-4 days |
| Bundle ID rename `ai.smallest.uxie → ai.uxie.app` | forces one-time-reinstall | 1 day |

## Production-readiness status

**Ready (use today):**
- Code paths shipping at v1.4.0 — voice, meetings, tasks, briefings, referral
- Error reporting via Sentry — engine + renderer + backend all wired
- Privacy + ToS drafted (PRIVACY.md, TERMS.md)
- Auto-update pipeline rock solid
- Rate limits + burst limiters everywhere user-triggerable

**Pending — beta scale (≤100 users) works without these:**
- Domain + public landing page
- Google OAuth verification submission (currently in Testing mode → 100-user cap)
- Stripe / billing
- Analytics (PostHog or similar)

When you cross 80 active testers, start the domain + verification track
(~6 weeks). When you cross 200, finish billing. Until then, nothing
here is on fire.

## How to onboard a new tester

1. Add their Gmail address to Google Cloud Console → APIs & Services →
   OAuth consent screen → Test users → ADD USERS.
2. Send them the latest DMG URL from
   https://github.com/uxie-app/uxie-releases/releases.
3. They install, run, sign in via OTP. Existing flows handle the rest.

## The six files that matter if reviving

| File | What lives there |
|---|---|
| [miniflow-engine/agent.py](miniflow-engine/agent.py) | Hotkey command path. Tool registry. Transform + formatting. System prompts. |
| [miniflow-engine/audio_meeting.py](miniflow-engine/audio_meeting.py) | Meeting recording — spawns Swift tap, pipes PCM to Deepgram, appends transcripts. |
| [miniflow-engine/meeting_watcher.py](miniflow-engine/meeting_watcher.py) | Auto-detection — `--watch` mode, parses window-presence events, fires meeting:detected. |
| [native-helper/audio-tap/Sources/UxieAudioTap/main.swift](native-helper/audio-tap/Sources/UxieAudioTap/main.swift) | Single Swift binary with two modes: audio capture + window watcher. |
| [uxie-backend/tasks.py](uxie-backend/tasks.py) | Background-task agent loop on Railway. Approval gate. Parallel tool exec. |
| [uxie-backend/scheduled_tasks.py](uxie-backend/scheduled_tasks.py) | TEMPLATE_REGISTRY + cron worker for Briefings. Morning brief, evening recap, weekly digest generators all here. |
| [uxie-backend/connectors/google.py](uxie-backend/connectors/google.py) | Gmail + Calendar + Drive tools as HTTP calls with 401-refresh-retry. |
| [uxie-backend/connectors/slack.py](uxie-backend/connectors/slack.py) | Slack search / send / read tools. |

## Environment variables — what needs to be set

**Railway (uxie-backend service):**
```
DATABASE_URL          (auto-provided by Railway Postgres)
JWT_PRIVATE_KEY       (RS256 PEM)
JWT_PUBLIC_KEY        (RS256 PEM)
RESEND_API_KEY        (for OTP + briefing emails)
GROQ_API_KEY
OPENAI_API_KEY
DEEPGRAM_API_KEY
DEEPGRAM_PROJECT_ID   (for ephemeral key minting)
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
SLACK_CLIENT_ID       ← optional; if missing, /oauth/slack/start 500s clearly and UI hides the Connect Slack button
SLACK_CLIENT_SECRET   ← same
SENTRY_DSN            (the backend Sentry project DSN)
ADMIN_EMAILS          (comma-separated, for /admin/*)
```

**Engine + renderer (DSN baked into binary at build time):**
- Engine Sentry DSN — hardcoded in `miniflow-engine/main.py`, overridable via `SENTRY_DSN` env var
- Electron Sentry DSN — hardcoded in `miniflow-electron/src/main/index.ts`

## When in doubt

Read [PROCESS.md](PROCESS.md). It has the change-and-release lanes
(Quick / Standard / Full / Release / Hotfix) and the project-specific
landmines that have bitten us. Skipping lanes is how we ship the next
React-hook bug.

## Final tag

**v1.4.0** = closing release. Everything in the "Shipped" table is
included. Future patches go in v1.4.x.
