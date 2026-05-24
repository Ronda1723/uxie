# Uxie — Privacy Policy

Last updated: 2026-05-24

This is a plain-language summary of what Uxie does with your data. The
short version: we collect as little as possible, store it on your
device when we can, route through our backend only when an LLM needs
to see it, and never sell anything.

## What Uxie collects

**On your device** (`~/miniflow/` on macOS):
- Dictation transcripts and command history (local SQLite)
- Meeting transcripts and structured notes (local SQLite at `meetings.db`)
- OAuth refresh-tokens (macOS Keychain only)
- App preferences, hotkey config, dictionary entries, snippets

**On our backend** (Railway, USA-region):
- Your email address (for sign-in via OTP)
- A JWT identifying your account, with a 30-day expiry
- OAuth tokens for Google / Slack — held server-side so they're not
  shipped in the .dmg
- Per-month usage counters (dictation, command, structure-meeting)
- Anonymized telemetry of LLM calls (provider, model, token counts,
  latency) for billing reconciliation
- For diagnostic purposes only: transcripts of dictation/commands that
  pass through `/llm/stream` and `/llm/chat`. Retained 30 days, then
  purged. Used to investigate "Uxie misheard me" reports. Never used
  for model training. Stored encrypted at rest.

**On third-party services**:
- Deepgram (speech-to-text): we proxy short-lived ephemeral keys so
  Deepgram sees the audio stream but not your account. Deepgram does
  NOT retain audio per our project config.
- Groq (LLM, used for dictation): receives the text-only transcript
  for grammar correction. Groq's policy: no data retention for API
  customers.
- OpenAI (LLM, used for commands): receives the text-only transcript
  + tool definitions. OpenAI's policy: API data is not used to train
  models.
- Resend (email): handles OTP emails + your scheduled Briefings if
  email delivery is enabled. Resend retains email metadata 30 days.
- Sentry (error reporting): receives stack traces + a per-user opaque
  ID when Uxie crashes. We strip PII before sending.

## What Uxie does NOT collect

- Your speech audio after transcription (discarded immediately)
- Your screen contents (we never capture video; meeting recording is
  audio-only)
- Your keystrokes outside of dictation sessions
- Your location, contacts, calendar attendees beyond what you've
  granted via Google OAuth
- Anything for advertising — Uxie has no ad surface

## Where your data lives

- **Local-first by default.** Transcripts, meetings, notes all live in
  `~/miniflow/` on your Mac.
- **Backend (Railway)** holds OAuth tokens, JWT, usage counters, and
  diagnostic transcripts.
- **No data sale.** We do not sell or rent any user data to any third
  party. Ever. (This is a single-developer indie project — there's no
  business model that involves your data.)

## Permissions Uxie asks macOS for

- **Microphone** — for dictation + meeting recording (your voice only)
- **Accessibility** — to type the corrected text back into your active
  app
- **Input Monitoring** — to detect the `fn` hotkey press
- **Screen Recording** — for ScreenCaptureKit to capture system audio
  during meetings (other participants' voices). NO video is captured.
- **Notifications** — for meeting-detection alerts and Briefings

You can revoke any of these at any time in System Settings → Privacy
& Security. Uxie will degrade gracefully (dictation works without
Screen Recording, meeting transcription becomes mic-only, etc).

## Your rights

- **Export**: open `~/miniflow/` in Finder — everything is plain text
  / SQLite. You can copy / migrate / inspect at any time.
- **Delete**: quit Uxie, drag `~/miniflow/` to Trash, uninstall the
  .app. Local data is gone. Email `rounak@smallest.ai` to delete your
  backend account + all server-side data; we'll confirm within 7 days.
- **Disconnect a provider**: Settings → Connectors → Disconnect on the
  service you want gone. Backend deletes the OAuth token row
  immediately. Email Google/Slack to verify revocation on their side
  if you want belt-and-braces.

## Children

Uxie is not directed at children under 13 and we do not knowingly
collect data from them. If you believe we have, email
`rounak@smallest.ai` and we'll delete it.

## Contact

Questions, concerns, deletion requests:
**rounak@smallest.ai**

We'll respond within 7 business days.

## Changes to this policy

We'll update this file in the GitHub repo and bump the date at the
top. Material changes get announced in-app via a one-time dialog
before they take effect.
