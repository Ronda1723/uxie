# Uxie — Design System + Product Decisions

> Living document. Every design decision and every product decision in
> this file is paired with the reasoning that justified it. If you find
> yourself about to change something here, read the *why* first — you may
> be re-litigating a closed conversation.

*Single-developer indie product. Last updated 2026-06-06. v1.5.1+ in production beta.*

---

## Table of contents

1. [North-star principles](#1-north-star-principles)
2. [Visual language](#2-visual-language)
3. [Components](#3-components)
4. [Interaction patterns](#4-interaction-patterns)
5. [Information architecture](#5-information-architecture)
6. [Product decisions](#6-product-decisions)
7. [Anti-patterns](#7-anti-patterns)

---

## 1. North-star principles

These five drive every concrete decision below.

### 1.1 Voice is the primary input, visual is the fallback

**Decision:** The hotkey (`fn` on Mac, Right-Alt on Windows) is the front door. The Mac window with tabs is the back office — where you review what voice already did.

**Why:** Typing into a chat box is the wrong primary UX for AI in 2026. The user knows what they want to say faster than they can type it. Once a user dictates emails for a week, they don't go back. The hotkey is the wedge habit that makes everything else sticky.

**Implication:** Spend visual real estate on *reviewing and approving* (Tasks tab, Meetings tab, Briefings tab) — not on typing prompts. The Tasks tab's textarea exists because some tasks are too complex for voice, but it's the secondary entry point, not the primary.

### 1.2 OS-level depth, not a sandboxed surface

**Decision:** Uxie is a real Electron + Swift + Python app with macOS Accessibility API access, ScreenCaptureKit permissions, frontmost-app awareness, system clipboard control, native notifications. Not a Chrome extension. Not a web app.

**Why:** The moat is what the browser can't do. Capturing system audio, typing into any window, watching meeting windows appear — these are how Uxie is fundamentally more useful than ChatGPT desktop. Lose this and Uxie is just another chatbot.

**Implication:** Every release carries the cost of real native engineering — TCC permissions, code signing, notarization, two operating systems. Worth it. Don't propose features that drift away from this — e.g. "let's make a web version too" is a no.

### 1.3 Ambient > reactive

**Decision:** Three scheduled briefings (Morning / End-of-Day / Weekly) fire on their own. Auto-detection runs in the background. Background tasks survive Mac sleep on Railway. The Mac client polls for updates.

**Why:** Every other AI tool is reactive — wait to be asked. The product that wins is the one that initiates: *"Sarah replied — want a draft?"* *"You have 3 hours of meetings tomorrow with no prep — should I generate a briefing?"* Wake up to a brief delta on your day, don't write the prompt to get one.

**Implication:** Build the cron + watcher infrastructure even before the features themselves feel "necessary." It's the underlying habit-forming layer.

### 1.4 Trust is earned through approval, not assumed

**Decision:** Every destructive action — `gmail_send`, `slack_send_message`, `calendar_create_event` — gates on an approval card with editable inline params before execution. The approval card is the central trust mechanism, more important than the chat history.

**Why:** An agent that just executes is a footgun. The moment a user trusts the agent with one risky action, they trust it with ten. That trust is built per-approval, not declared. *"Uxie wanted to send this email, I read it, I clicked Approve"* is fundamentally different from *"Uxie sent an email and I'm seeing it in Sent now"*.

**Implication:** Never ship a feature that bypasses approval for destructive actions. The 5-minute auto-decline timeout exists so a forgotten gate doesn't pin a worker forever, not so users can skip approval.

### 1.5 Patience > velocity

**Decision:** Each release goes through PROCESS.md's lanes (Quick / Standard / Full / Release). React-hook bug in v1.0.29 happened because we skipped lanes. Don't do that again.

**Why:** A release that rolls back is cheaper than a release that ships late. But a release that ships broken to users in the field — when you have no Sentry, no error reporting, no in-app feedback channel — costs you compound trust. The hotfix-and-bisect cycle around v1.5.0 (Deepgram params) is the cost of skipping the "verify the actual handshake before shipping" step.

**Implication:** Don't compress quality to ship features. Run typechecks. Smoke-test inside the bundle. Push backend first, verify, then push client. This isn't ceremony — it's how you keep ~50 trusted testers from quietly abandoning the app after one bad release.

---

## 2. Visual language

### 2.1 Color tokens

**Background hierarchy:**
- `#F3F3F1` — app background, warm cream
- `rgba(255, 255, 255, 0.4–0.6)` — translucent panel inserts (sidebar, cards) → lets the warm cream show through subtly
- `rgba(0, 0, 0, 0.03)` — pre boxes / inline code blocks / muted state cards

**Text hierarchy:**
- `#1a1a1a` — primary text (near-black, never pure black — pure `#000` reads as harsh in macOS-native context)
- `#444` — body content inside dark panels
- `#666` — secondary text, captions
- `#888` — tertiary / placeholder / empty states
- `#3367d6` — link blue (matches macOS system link color closely)

**Status pill palette (uniform shape, color per state):**

| State | Hex | Used for |
|---|---|---|
| Active / Recording / Approved / Success | `#3a8c6a` (green) | Toggle ON, meeting in progress, approval accepted |
| Running / Working / In-progress | `#3367d6` (blue) | Task running, brief generating |
| Pending / Needs attention / Idle-detected | `#F4A21B` / `#b87100` (amber) | Approval needed, meeting detected but not recording |
| Failed / Declined / Destructive / Error | `#d44a4a` (red) | Task failed, approval declined, delete button |
| Structured / Completed / Premium-state | `#7a5cd1` (purple) | Meeting has structured notes, "structured" status |
| Idle / Skipped / Paused | `#5b6878` (gray-blue) | Skipped meeting, paused schedule |

**Pill background formula:** `color + 22 (hex alpha 0.13)`. So an active pill is `background: rgba(58, 140, 106, 0.13); color: #3a8c6a`. Low visual weight, color carries meaning, not loudness.

**Why warm cream over pure white:**
*Tested both. Pure white reads as "AI dashboard / Linear / Notion" — cold, productivity-tool. Warm cream reads as "real software for a real person." Sets the tone — "this is your AI, not your company's CRM."*

**Why 5 distinct status colors:**
*Tested 3 (success / failure / pending) — too coarse. 7+ — users couldn't keep them straight. Five is the sweet spot: green/red are universal, amber is "human-in-loop", blue is "machine working", purple is "premium completed state." Gray fills "this exists but doesn't need you."*

### 2.2 Typography

- **Stack:** `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. No custom webfont.
- **Sizes:** 11 / 12 / 13 / 15 / 18 / 22 px. Five steps total.
  - 22 — tab page titles ("Meetings", "Tasks", "Briefings")
  - 18 — meeting / task detail page titles
  - 15 — card titles ("Morning Brief", section heads inside cards)
  - 13 — body text, list items, dates
  - 12 — secondary text, body inside cards
  - 11 — captions, status text, dates
  - 10 — section labels (always uppercase)
- **Code/monospace:** `ui-monospace, "SF Mono"` — for IDs, technical strings, transcript pre blocks
- **Section labels:** `font-size: 11px, text-transform: uppercase, letter-spacing: 0.05em, font-weight: 700, color: #888`. Used for "ACTIVITY", "TRANSCRIPT", "STRUCTURED NOTES", "INBOX HIGHLIGHTS".

**Why system font:**
*Custom webfonts add a font-loading flash, FOUT/FOIT artifacts, and force Mac users into a non-native typographic experience. System font is fast, free, and matches the native OS instantly. The visual identity of Uxie is the layout + color, not the font.*

**Why uppercase section labels:**
*Acts as a visual divider without adding a border or rule. Letter-spacing 0.05 + uppercase + tiny size + muted color = "this is a label, the content below it is what matters." Used consistently across MeetingsTab, TasksTab, BriefingsTab so the user learns the pattern once.*

### 2.3 Spacing

- **Grid:** 4-point base. Most things in multiples of 4: 4 / 8 / 12 / 16 / 24 / 32.
- **Card padding:** 16px internal (12px in dense areas like sidebar rows).
- **Card-to-card gap:** 12-16px vertical.
- **Section-to-section gap:** 24px.
- **Page padding:** 20-24px around the main content area.

**Why 4-point base:**
*8-point grid is the industry default but feels too coarse for our dense UI. 4-point gives tighter control over status pills and pill rows. Most components round to 8 anyway — 4 is the exception for tight spacings, not the rule.*

### 2.4 Border + radius

- **Radius:** 6px (buttons, input fields, small cards) / 8px (large cards / sections) / 10-12px (modal envelopes, status pills) / round (circular avatars)
- **Border:** `1px solid #e5e3df` for default card edges; `1px solid rgba(0,0,0,0.06)` for inline boxes
- **Shadow:** rarely used. Uxie's visual hierarchy is built with borders + spacing, not shadows. The exception is the floating capsule (hotkey overlay) which has a subtle shadow for elevation.

**Why minimal shadows:**
*Shadow-heavy UIs feel "Material" or web-app-ish. The macOS-native look is built on borders + light backgrounds. Granola also uses near-zero shadow. Sets the right tone.*

---

## 3. Components

### 3.1 Status pill

**Visual:** Rounded (10px), 11px font, 600 weight, uppercase, letter-spacing 0.04. Two layers: colored text on `color@13%` background.

**Usage rules:**
- Every entity with a state has a pill (meetings, tasks, schedules, OAuth connections)
- Always uppercase
- Single word ideally; max two ("NEEDS YOU" yes, "WAITING FOR USER" no)
- Position: top-right of the entity's container

**Why uppercase + uniform shape:**
*The pill is the universal UX vocabulary across the app. User learns the visual grammar once: amber = needs me, green = healthy, gray = idle, red = broken. This is how a complex agent product stays cognitively cheap to navigate. Mixed-case pills would feel like buttons; uppercase reads as "label, not action."*

### 3.2 Approval card

**Visual:** Amber-tinted background (`rgba(244, 162, 27, 0.08)`), 1px amber border at 40% opacity, 8px radius, 12px internal padding.

**Anatomy:**
- Top row: `APPROVAL NEEDED` label (amber, uppercase) + tool name as code on the right
- Middle: human-readable summary (e.g. "Send email to john@example.com — subject: Meeting Tomorrow at 4")
- Collapsible `<details>`: editable inline form fields for every param (to, subject, body, etc.)
- Bottom row: **Approve** (filled black) + **Decline** (outlined gray)

**Why amber, not red:**
*Red would read as "danger / error" — stressful. Amber reads as "pause and decide" — the right emotional pitch for "your AI wants to send something on your behalf." Yellow-amber is the universal "caution, slow down" color.*

**Why editable params inline:**
*The first thing a user does when the AI drafts an email is fix a typo in the recipient or the body. If they have to decline, edit the prompt, re-run — that's 3 round-trips. If they can fix it inline and approve, it's 1. Drastically improves the perceived intelligence of the agent.*

**Why a 5-min auto-decline timeout:**
*A forgotten gate would otherwise pin the worker forever. 5 min is enough for "I went to grab coffee mid-approval" but not so long that a stuck task wastes resources. We arrived at 5 min after testing 60s (too short — users hit it just by reading the summary) and 15 min (too long — stuck workers piled up).*

### 3.3 Two-pane list + detail layout

**Used in:** Tasks tab, Meetings tab

**Visual:**
- Left rail: 280-320px fixed width, scrollable, `rgba(255,255,255,0.4)` translucent background, 1px right border
- Right pane: flex-1, scrollable, 20-24px page padding
- Each list item: 10-12px vertical padding, 16px horizontal, 1px bottom border at `rgba(0,0,0,0.04)`

**Why two-pane:**
*The user mostly wants to scan a list and dive into one item. Single-column forces them to scroll back and forth. Two-pane gives them context (list visible while detail open) — same UX as Mail.app, Notion, Linear. Familiar pattern, low cognitive cost.*

**Why list on the left, not right:**
*Latin-script reading direction. Eye lands top-left first. Most-important context (which item am I looking at) belongs there.*

### 3.4 Sidebar tabs (left rail)

**Visual:**
- 200-240px wide, full-height
- Logo + "Uxie" header at top, traffic lights row above it
- Tab rows: icon (emoji or unicode) + label, 10-12px vertical padding, hover highlights, active state with subtle filled background
- Spacer pushes Settings + Help to the bottom

**Order rationale:**
1. **Home** — landing, the calm state
2. **Tasks** — actively working (high frequency for power users)
3. **Briefings** — schedule + history (less frequent but important)
4. **Meetings** — review (passive, post-event)
5. **Dictionary** + **Snippets** — config (rarely visited)

The order roughly matches *frequency of revisit* descending. Power-user features at top, configuration at bottom.

**Why emoji icons:**
*Custom icons would add work + a consistent visual system. Native emoji gives us instant icons that adapt to OS-level emoji rendering (matching the user's Mac). Plus emoji read better in long-form context — "⚡ Tasks" feels punchier than a gray glyph that needs SVG infrastructure.*

### 3.5 Template card (briefings)

**Visual:**
- 8px radius card, 16px padding, `rgba(255,255,255,0.6)` background, 1px `#e5e3df` border
- Top row: card title + status pill (Active / Paused) OR "Set up" CTA
- Collapsible body: time picker + timezone + delivery toggles + action buttons + last-fired timestamp
- One-line description below the title in muted 12px

**Why collapsible by default when not set up:**
*Three templates × an expanded form each = visual overwhelm on first visit. Collapsed lets the user scan all three first, pick the one to set up, expand that one. After setup, the active state stays expanded so the user can quickly toggle / adjust without re-expanding.*

### 3.6 Floating capsule (hotkey overlay)

**Visual:**
- ~280px wide, 60-80px tall, anchored to bottom-center of screen
- Dark translucent background, white text, rounded ends
- Animated waveform left + live interim transcript right
- Slides up from bottom edge on `fn` press (~250 ms spring), morphs in width as transcript grows, slides down on release

**Why anchored to the bottom, not center or top:**
*The user is focused on their primary app — Mail, Notion, Slack — which usually has content at the top. Bottom-screen capsule doesn't occlude the work surface. It also matches macOS conventions for transient UI (notifications, AirDrop overlays).*

**Why animated waveform:**
*Without it, user can't tell if Uxie is actually hearing them. Silent capture is anxiety-inducing. The waveform is RMS-driven from the actual mic input — visible feedback that audio is flowing.*

---

## 4. Interaction patterns

### 4.1 Hotkey as the universal entry point

`fn` (Mac) / Right-Alt (Windows) → speak → release.

- *Hold-to-talk* (push-to-talk), not toggle-to-record. Toggle invariably leads to "did I leave the mic on?" anxiety.
- Bundle ID + frontmost-app + selected text are captured at press-time, before the capsule even shows up, so context is locked even if the capsule steals focus.
- Selection is read via Accessibility API at press, so "polish this" knows what `this` is by the time the user finishes speaking.

**Why `fn` on Mac:**
*Available on every Mac, single-key, doesn't conflict with anything else, naturally falls under the left thumb without contorting the hand. Globe key (`fn` on newer keyboards) maps to the same scancode. Tried Cmd+Space (collision with Spotlight), Cmd+Shift+V (collision with paste-special), Option+Space (collision with AppleScript) — `fn` is the unowned default. The native macOS dictation hotkey too, which is fitting.*

### 4.2 Polling-based progress, not streaming

**Decision:** TasksTab polls `/tasks/{id}` every 2s while a task is running. BriefingsTab polls `/scheduled_tasks` every 60s. MeetingsTab subscribes via local WS for the active meeting's live transcript but polls the list otherwise.

**Why polling instead of SSE:**
*SSE / WebSockets across Mac → Railway add complexity for a single-tester product. Polling at 2s is functionally identical to streaming for "watch a task run" UX — the user can't perceive the difference between 2s and 200ms. The complexity savings (no reconnect logic, no presence detection, no auth-stream headers) are real.*

**Why 2s and not 5s:**
*Tested 5s — felt laggy. Tested 1s — burned mobile data + Railway egress. 2s was the sweet spot for "feels responsive."*

### 4.3 Approval gates always inline, never modal

**Decision:** Approval cards appear *inside* the activity log of a task, not as a modal popup over the app.

**Why inline:**
*A modal breaks the user's flow — they have to deal with it or dismiss it. An inline card sits in context: the user can scroll the activity log, read past steps, then decide on the approval card without losing place. Multiple pending approvals (a complex task with 2-3 destructive steps) stack naturally as separate cards in the same log instead of as a queue of modals.*

### 4.4 Voice-driven notifications, not popovers

**Decision:** When a meeting is detected, we fire a native macOS notification with action buttons — not an in-app popover.

**Why:**
*The user may not have Uxie's window visible when a meeting starts (they're probably looking at the meeting app itself). The macOS notification surface is where users already look for time-sensitive prompts. Action buttons let them respond without context-switching to Uxie.*

### 4.5 Live interim transcripts in meetings

**Decision:** Italic gray text below the committed transcript shows what's being said *right now*, replaced when the final lands.

**Why:**
*Without it, users felt like the app froze for 10+ seconds during meetings (the pre-v1.5.0 Deepgram default-endpointing bug). Even after the latency fix, having a visible "live" indicator confirms the system is hearing them. Italic + gray signals "this might change" — the user learns not to copy from this line because it'll get replaced.*

---

## 5. Information architecture

### 5.1 Tab strategy

Uxie's left rail has 6 tabs. That's already at the upper bound of healthy nav menu length. Future features should ask: *does this need a new tab, or can it live inside an existing one?*

- **Home** is a placeholder for status / branding. Could become a "what's happening now" dashboard in the future.
- **Tasks** and **Briefings** are sister tabs — both are "agent doing async work," but Tasks is *user-initiated*, Briefings is *time-initiated*. Splitting them aids discoverability ("how do I make my AI do something now" vs "how do I make my AI do something every morning").
- **Meetings** stands alone. The recording + review flow is too distinct from agent tasks to merge.
- **Dictionary** + **Snippets** are config. Could be moved into Settings if we ever get a 7th tab worth shipping.

### 5.2 Settings vs main tabs

**Rule:** "Things you do" go in the left rail. "Things you set once" go in the Settings modal.

So: meetings → tab. Briefings → tab. Tasks → tab.
But: OAuth connectors → Settings. Hotkey rebind → Settings. Account info + invite code → Settings.

**Exception:** "Auto-detect meetings" toggle lives in the Meetings tab as a small banner, not Settings. *Because it's contextual to the feature — discoverability beats taxonomic purity.*

### 5.3 Approval surface

Lives in *three* places:
1. **Inline in the Tasks activity log** — for background-task destructive actions
2. **As a floating overlay window** — for voice-command destructive actions (when user just spoke a command and needs to confirm before the email goes)
3. **Native macOS notification** — for meeting detection (record / skip)

**Why three surfaces:**
*Each maps to a different user attention state. Background task → user is in the Tasks tab reviewing → inline is right. Voice command → user just spoke → overlay near their current focus. Meeting detection → user is probably in another app entirely → notification at OS level.*

---

## 6. Product decisions

### 6.1 Three baked-in briefing templates (not one, not user-creatable)

**Decision:** Ship Morning Brief / End-of-Day Recap / Weekly Digest. Don't let users create their own templates yet.

**Why not just one:**
*Morning Brief alone leaves a huge value gap. Users have asked for "what did I do today" (end of day) and "what's my week look like" (weekly) often enough that they're worth pre-building.*

**Why not user-creatable templates:**
*Three is enough to prove the concept. User-creatable templates require a UI for prompt editing, a UI for scope selection, a way to test before scheduling. That's a 2-week feature. Defer until users complain.*

### 6.2 Background tasks default to read-only tools; destructive ones gate on approval

**Decision:** Background tasks can call `gmail_search`, `gmail_read`, `calendar_list_events`, `drive_search`, `drive_read`, `slack_search` freely. They CAN call `gmail_send`, `slack_send_message`, `calendar_create_event` but only after explicit user approval.

**Why split:**
*If background tasks could auto-execute destructive actions, one bad agent loop or one prompt-injected email could mass-send spam. Read-only tasks are safe to auto-execute — worst case is wasted tokens. Destructive ones need a human in the loop.*

### 6.3 Local-first meeting transcripts, opt-in upload to admin

**Decision:** Meeting transcripts + audio stay on the user's Mac by default. Admin dashboard upload is an opt-in toggle in Settings → Account.

**Why:**
*Granola's privacy stance is "audio discarded, transcripts local." That's the table-stakes for the meeting recorder category. Defaulting to upload would scare away users who care about confidentiality. Opt-in upload exists for users (or admins) who want centralized access for debugging.*

### 6.4 Polling, not streaming

Covered above (§4.2). Decision: chose polling because the engineering complexity savings outweighed the marginal latency benefit.

### 6.5 Email + macOS notification for briefings, not in-app only

**Decision:** Briefings deliver via two channels — macOS notification (transient) + email (persistent).

**Why both:**
*Notification is good for "I should read this now." Email is good for "I want to scroll back later." Both also serve different mental models — some users live in their inbox, others ignore email. Letting the user toggle each independently respects both.*

### 6.6 Hardcoded keywords vocabulary list

**Decision:** The Deepgram `keywords=` boost is sourced from a hardcoded list ("Uxie", "Smallest", "Granola", "Slack") plus the user's first name. Not from any dynamic source like calendar attendees or address book.

**Why hardcode (for now):**
*Calendar attendee scraping has privacy implications + adds query complexity. Address book on Mac requires another permission grant. Hardcode covers 80% of the high-value boost cases (company name, product name, user name) without the engineering cost. Plan to widen in v1.6+ once we know users actually feel the gain.*

### 6.7 Refresh tokens via Composio path NOT chosen (yet)

**Decision:** Stayed with own Google OAuth implementation; deferred Composio migration.

**Why:**
*Own OAuth works today for ≤100 users in Testing mode. Composio's value (skip Google verification, get connectors free) is real but adds vendor lock-in + per-call cost. Defer the swap until either (a) verification timeline becomes a blocker for launch, or (b) we want >5 new connectors quickly. Documented as an option in case-study.md for future decision.*

### 6.8 No notch UI (yet)

**Decision:** The notch on newer MacBook Pros is a tempting always-visible status surface, but deferred.

**Why:**
*Notch real estate is small (~200pt wide) and only available on M2+ MacBook Pro. Non-notch users (Air, older Pros, external monitors) need a fallback. Building both would be ~2 weeks. Visual cohesion gain is real but doesn't unlock new functionality — the floating capsule serves the same status role. Revisit when we have >50% of users on notch-capable hardware.*

### 6.9 The Swift sub-bundle approach for audio capture

**Decision:** Audio capture lives in a separate Swift `UxieAudioTap.app` inside `Uxie.app/Contents/Resources/`. Not in the main Electron process. Not in a raw CLI binary.

**Why:**
*ScreenCaptureKit + AVCaptureSession need TCC permissions. Raw CLI binaries don't have an Info.plist for TCC to read usage descriptions from → silent rejection. Wrapping the Swift binary in a tiny .app sub-bundle gives TCC something to attach permissions to. Discovered through painful iteration in v1.0.31-32 (multiple AVAudioEngine-fails-in-CLI-mode rounds); documented in STATE.md.*

### 6.10 Why three Sentry projects, not one

**Decision:** Engine + Renderer + Backend each get their own Sentry project.

**Why:**
*Different surfaces have different error volumes and different debug contexts. A Python KeyError in the engine doesn't share much with a React render crash in the renderer. Three projects let us set separate alerts, separate volume budgets, and avoid cross-noise. One project would be ~30% cheaper but ~70% harder to triage.*

### 6.11 Bundle ID still `ai.smallest.uxie`

**Decision:** Legacy bundle ID kept; future migration to `ai.uxie.app` deferred.

**Why deferred:**
*Bundle ID rename forces a one-time reinstall — all existing users have to download a new .dmg. That's a tax we don't want to pay until we have a real reason (e.g. public launch + clean brand). For private beta, the bundle ID is invisible to users; the Dock label says "Uxie" either way.*

### 6.12 Default audio retention ON for meetings

**Decision:** Audio for meetings is saved by default to `~/miniflow/meetings_audio/<id>.wav`. User has to manually delete or wipe the folder.

**Why ON by default:**
*Without local audio, the user can't replay meetings — only read transcripts. Transcripts are often imperfect; replay is the safety net. Disk cost is real (~115 MB/hour) but bearable on modern Macs (1 TB drives are standard). Users with disk pressure can delete via the Meetings tab's Delete button, which also wipes the WAV.*

**Why not opt-in:**
*Opt-in would mean most users miss the feature entirely. Users who want this only after they've recorded a few meetings and realized transcripts have errors — at which point the audio is gone. Default ON, opt-out trivial.*

### 6.13 Three brief templates ship Markdown, not rich HTML

**Decision:** Brief generators output plain Markdown. Email rendering wraps it in `<pre>` so Gmail respects linebreaks.

**Why:**
*Markdown is universally readable. Rich HTML email is finicky across Gmail / Outlook / Apple Mail. Markdown looks "professional but informal" — right tone for a brief. The `<pre>` wrapper sacrifices fancy heading styles but guarantees readable structure everywhere.*

### 6.14 OAuth connection lives on backend, not in DMG

**Decision:** Provider OAuth tokens (Google, Slack) are held server-side on Railway, not packaged inside the .app.

**Why:**
*If we packaged `GOOGLE_CLIENT_SECRET` inside the .dmg, every distributed copy would have the same secret in clear text in its bundle. Anyone could extract it and impersonate the app. Railway holding the secret means even reverse-engineering the .app doesn't compromise the OAuth client. Clients send their JWT to Railway; Railway calls Google with the secret.*

### 6.15 Adopted `interim_results=true&endpointing=300` for meetings — discovered through bug

**Decision:** Meeting STT uses interim partials + 300 ms endpointing.

**Why (with bug history):**
*Original code had `interim_results=false` + no `endpointing=` set, which fell through to Deepgram's default ~10s VAD turnoff. Transcripts appeared 10+ seconds late. Users called it "broken." Fix in v1.5.0 enabled interim_results + tightened endpointing. v1.5.1 hotfix had to revert three other params we tried in the same release; lesson: tune one param at a time, verify handshake before tagging.*

### 6.16 Sentry init code path bakes the DSN at build time

**Decision:** Engine and Electron renderer ship with hardcoded Sentry DSNs; backend uses env var.

**Why:**
*Sentry DSNs are public credentials — they're meant to be in client-side code. Hardcoding lets every shipped .dmg phone home with errors immediately without manual env-var setup. Backend DSN is env-var-driven because Railway env vars are easier to update than a code change for the same purpose.*

---

## 7. Anti-patterns

Things we tried and explicitly chose not to do.

### 7.1 Modal popups for every interaction
*Tried in early v1.0.x. Users hated context-breaking modals. Replaced with inline cards + native notifications.*

### 7.2 Plugin marketplace
*Premature at single-digit user count. Maintenance burden of curating 3rd-party connectors would dwarf core feature work.*

### 7.3 Custom font
*Considered Inter / GT America. Decided system font is faster + matches macOS native experience.*

### 7.4 Multi-tone branding (multiple accent colors)
*Tried purple + green + amber as co-equal brand colors. Visually loud. Settled on near-black as primary action color, with semantic status colors only.*

### 7.5 Showing every Deepgram word + timestamp in the UI
*Tried rendering word-level data. Way too much information for users to parse. Settled on utterance-level transcript with Speaker N labels.*

### 7.6 In-app chat history surface
*Building a "ChatGPT-style history" view was on the roadmap. Decided against — the natural memory surface is *contextual* ("what did Sarah say about pricing") not chronological. Defer to a future memory layer.*

### 7.7 Always-on screen recording for "remember everything"
*Tested in prototype. Privacy + battery + storage costs dwarf the recall benefit. Stuck with explicit-record-mode.*

### 7.8 Voice as the only input
*Initially considered making the Tasks tab voice-only. Some tasks are too complex to dictate without errors. Keep the textarea as a secondary entry — voice is primary, text is fallback.*

---

## 8. How to build new UI

The practical companion to §2-3. If you're adding a new screen or
component, this section is the checklist.

### 8.1 File structure

```
miniflow-electron/src/
├── main/                        Electron main process
│   ├── index.ts                 entry — wires hotkey, helper, ws, ipc
│   ├── ipc.ts                   ALL IPC handlers (one per renderer→engine call)
│   ├── tray.ts                  menu-bar + popover window
│   ├── overlayWindow.ts         floating capsule (hotkey overlay)
│   ├── meetingNotifications.ts  native macOS notifications
│   ├── websocket.ts             local WS bridge engine → renderer
│   └── widgetState.ts           floating-capsule state machine
├── preload/
│   └── preload.ts               EVERY window.miniflow.* method declared here
├── renderer/
│   ├── App.tsx                  top-level — tab switching + onboarding gate
│   ├── main.tsx                 React root + Sentry init + ErrorBoundary
│   ├── styles.css               legacy CSS (sidebar nav, modal envelope, fields)
│   ├── audio.ts                 useAudioCapture hook (renderer mic)
│   ├── overlay.tsx              floating capsule UI
│   └── components/
│       ├── Sidebar.tsx          left rail — add new nav-item here
│       ├── HomeTab.tsx          first-load landing
│       ├── TasksTab.tsx         background tasks (two-pane)
│       ├── BriefingsTab.tsx     scheduled workflows (template cards)
│       ├── MeetingsTab.tsx      meetings (two-pane)
│       ├── DictionaryTab.tsx    word substitutions
│       ├── SnippetsTab.tsx      text expansion triggers
│       ├── SettingsModal.tsx    modal with nested tabs (Account/Connectors/Invite/Hotkey/Updates)
│       ├── OverlayWidget.tsx    approval overlay (floats over the focused app)
│       ├── Onboarding.tsx       first-launch flow (email + OTP + permissions)
│       └── ApprovalWidget.tsx   inline approval card (used in Tasks)
└── shared/
    └── types.ts                 IpcChannels enum + shared TS types
```

**Rule:** a new feature usually adds ONE file under `components/` and
one entry in `App.tsx` + `Sidebar.tsx`. Don't sprawl across folders for
a single feature.

### 8.2 Styling approach (live state, with rationale)

Uxie uses **two coexisting style systems** — pick the right one per use case:

1. **Inline `React.CSSProperties` objects** (preferred for new components).
   Style constants live at the bottom of the component file. Used by
   TasksTab, BriefingsTab, MeetingsTab. No external CSS file dependency,
   no class-name collisions, easy to fork for component variants.

2. **CSS classes in `styles.css`** (legacy, used by the original Home / Sidebar
   / SettingsModal scaffolding). Stays around because the existing classes
   (`.modal`, `.modal-tab`, `.field`, `.row`, `.stack`, `.btn-secondary`,
   `.info-msg`) compose cleanly with native macOS aesthetic.

**Rule of thumb:** new isolated component → inline. Reusing modal /
form scaffolding → use the existing class. Don't introduce a new
component-styles file (Tailwind, CSS modules, styled-components, etc.)
without a strong reason — the current two-system setup works.

### 8.3 Reusable style constants — copy from these

Drop these at the bottom of any new component file. They're already
used in TasksTab / BriefingsTab / MeetingsTab — keep them identical so
the visual language stays consistent.

```tsx
const card: React.CSSProperties = {
  padding: 16, borderRadius: 8, border: "1px solid #e5e3df",
  background: "rgba(255,255,255,0.6)",
};

const sectionLabel: React.CSSProperties = {
  fontSize: 11, textTransform: "uppercase", letterSpacing: 0.05,
  color: "#888", fontWeight: 700, marginBottom: 8,
};

const fieldLabel: React.CSSProperties = {
  fontSize: 12, color: "#666", paddingTop: 7,
};

const input: React.CSSProperties = {
  padding: "6px 8px", borderRadius: 6, border: "1px solid #e5e3df",
  fontFamily: "inherit", fontSize: 13,
  background: "rgba(255,255,255,0.8)",
};

const btnPrimary: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "none",
  background: "#1a1a1a", color: "#fff", fontWeight: 600,
  cursor: "pointer", fontSize: 13,
};

const btnSecondary: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "1px solid #ccc",
  background: "transparent", color: "#1a1a1a",
  cursor: "pointer", fontSize: 13,
};

const btnDanger: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "1px solid #d44a4a",
  background: "transparent", color: "#d44a4a",
  cursor: "pointer", fontSize: 13,
};

const chipBtn: React.CSSProperties = {
  padding: "3px 8px", borderRadius: 12, border: "1px solid #e5e3df",
  background: "transparent", fontSize: 11, cursor: "pointer", color: "#666",
};

const preBox: React.CSSProperties = {
  whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13,
  padding: 12, borderRadius: 6, background: "rgba(0,0,0,0.04)",
  border: "1px solid rgba(0,0,0,0.06)", overflow: "auto",
};
```

### 8.4 Status pill component (canonical implementation)

Every new status indicator should follow this pattern:

```tsx
const STATUS_COLORS: Record<MyStatus, string> = {
  active:    "#3a8c6a",  // green
  running:   "#3367d6",  // blue
  pending:   "#F4A21B",  // amber
  failed:    "#d44a4a",  // red
  done:      "#7a5cd1",  // purple
  idle:      "#5b6878",  // gray-blue
};

function StatusPill({ status }: { status: MyStatus }) {
  const color = STATUS_COLORS[status] ?? "#888";
  return (
    <span style={{
      fontSize: 11, padding: "2px 8px", borderRadius: 10,
      background: color + "22", color, fontWeight: 600,
      textTransform: "uppercase", letterSpacing: 0.04,
    }}>
      {status}
    </span>
  );
}
```

Always uppercase. Always color@13% background (the `+ "22"` hex alpha).
Always positioned top-right of the entity's container.

### 8.5 Anatomy: a new tab in the left rail

Step-by-step, end-to-end. Pretend we're adding a "Memory" tab.

**Step 1.** Create the component. `src/renderer/components/MemoryTab.tsx`:

```tsx
import React, { useEffect, useState, useCallback } from "react";

const w = window as any;

export function MemoryTab() {
  const [items, setItems] = useState<any[]>([]);

  const refresh = useCallback(async () => {
    const r = await w.miniflow.listMemoryItems();
    setItems(r?.items ?? []);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <aside style={{
        width: 320, borderRight: "1px solid #e5e3df", overflow: "auto",
        background: "rgba(255,255,255,0.4)",
      }}>
        <div style={{ padding: "16px 16px 12px" }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Memory</div>
        </div>
        {items.map(it => (
          <button key={it.id} style={{
            display: "block", width: "100%", textAlign: "left",
            padding: "10px 16px", border: "none", background: "transparent",
            borderBottom: "1px solid rgba(0,0,0,0.04)", cursor: "pointer",
          }}>
            <div style={{ fontSize: 13 }}>{it.title}</div>
          </button>
        ))}
      </aside>
      <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
        <h1 style={{ fontSize: 22 }}>Memory</h1>
        <p style={{ fontSize: 13, color: "#666" }}>
          Things Uxie remembers about you and your work.
        </p>
      </div>
    </div>
  );
}
```

**Step 2.** Register it in `App.tsx`:

```tsx
// 1. Add to the SidebarTab union
export type SidebarTab =
  "home" | "tasks" | "briefings" | "meetings"
  | "memory"     // ← new
  | "dictionary" | "snippets";

// 2. Import the component
import { MemoryTab } from "./components/MemoryTab";

// 3. Render it inside the tab switch
{tab === "memory" && <MemoryTab />}
```

**Step 3.** Add the nav row in `Sidebar.tsx`:

```tsx
<div className={`nav-item ${activeTab === "memory" ? "active" : ""}`}
     onClick={() => onTab("memory")}>
  <span className="icon">🧠</span><span>Memory</span>
</div>
```

**Step 4.** Add the IPC + preload bridge if the new tab needs to talk
to the engine (most do). See §8.6.

That's it — four file touches for a new tab. No CSS, no build config,
no manifest changes.

### 8.6 Anatomy: a new IPC channel (renderer → engine)

Three files always:

**1.** `preload.ts` — declare the renderer-facing method:

```ts
listMemoryItems: () => ipcRenderer.invoke("memory:list"),
addMemoryItem:   (text: string) => ipcRenderer.invoke("memory:add", text),
```

**2.** `main/ipc.ts` — register the handler:

```ts
ipcMain.handle("memory:list", () => invoke("memory_list", {}));
ipcMain.handle("memory:add",  (_e, text: string) => invoke("memory_add", { text }));
```

**3.** `miniflow-engine/main.py` — add to the invoke dispatcher's
`handlers` dict:

```python
"memory_list": lambda b: memory.list_items(),
"memory_add":  lambda b: memory.add_item(b["text"]),
```

Plus implement `memory.py` (a new engine module) with the actual
business logic. If it talks to Railway, the function is async and
returns a JSON-able dict.

**Naming convention:**
- IPC channel: `feature:verb` (kebab-case area, colon, verb)
- Preload method: `verbFeature` (camelCase)
- Engine invoke key: `feature_verb` (snake_case)

### 8.7 Anatomy: a new Railway backend route

Three files in `uxie-backend/`:

**1.** `db_ios.py` — add the table (additive, no migration needed
because `init_db()` runs `create_all`):

```python
class MemoryItem(Base):
    __tablename__ = "memory_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**2.** `memory.py` (new file) — write the endpoint functions:

```python
async def list_items(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    rows = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == user.id)
        .order_by(desc(MemoryItem.created_at)).limit(100)
    )).scalars().all()
    return {"items": [_row(r) for r in rows]}
```

**3.** `main.py` — wire the routes:

```python
import memory as _memory  # noqa: E402
app.add_api_route("/memory",     _memory.list_items, methods=["GET"])
app.add_api_route("/memory",     _memory.add_item,   methods=["POST"])
```

JWT-gating is automatic via `Depends(current_user)`. Per-tier rate
limits via `check_and_increment(db, user, "command")` if it's a
non-trivial action.

### 8.8 Anatomy: a list + detail two-pane layout

The shape used by TasksTab + MeetingsTab. Crib from either when adding
a new entity-list view.

```tsx
function MyTab() {
  const [items, setItems] = useState<Item[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = items.find(i => i.id === selectedId) ?? null;

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <ItemList items={items} selectedId={selectedId} onSelect={setSelectedId} />
      <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
        {selected ? <ItemDetail item={selected} /> : <EmptyState />}
      </div>
    </div>
  );
}
```

**Conventions:**
- Left rail is 280-320px depending on row density (320 for tasks-with-prompts, 280 for meetings)
- Selected row gets `background: "rgba(0,0,0,0.06)"`
- Each row has 10-12px vertical padding, 16px horizontal
- Status pill on the right of each row, formatted timestamp on the left
- Empty detail state is gray italic text: *"Select a thing to see details"*

### 8.9 Anatomy: a card with form + actions (briefings template style)

When the user is configuring something (a scheduled task, a connector,
a preference), use this shape:

```tsx
<div style={card}>
  <div style={{ display: "flex", justifyContent: "space-between" }}>
    <h2 style={{ fontSize: 15, margin: 0 }}>Title</h2>
    <StatusPill status={status} />
  </div>
  <p style={{ marginTop: 6, fontSize: 12, color: "#666", lineHeight: 1.5 }}>
    One-line description of what this card does.
  </p>

  <div style={{
    display: "grid", gridTemplateColumns: "auto 1fr",
    gap: "12px 16px", marginTop: 16,
  }}>
    <label style={fieldLabel}>Field name</label>
    <input value={...} style={input} />
    {/* repeat label / input pairs */}
  </div>

  <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
    <button onClick={save} style={btnPrimary}>Save</button>
    <button onClick={remove} style={btnDanger}>Delete</button>
  </div>

  {error && <div style={{ marginTop: 12, color: "#d44a4a", fontSize: 12 }}>
    {error}
  </div>}
</div>
```

`gridTemplateColumns: "auto 1fr"` is the magic — labels auto-size,
inputs take the rest. Cleaner than flexbox for form layouts.

### 8.10 Common gotchas

- **Don't put hooks after early returns.** v1.0.29 shipped with this bug
  (React error #310). Hooks must be called unconditionally on every
  render. If you have `if (loading) return null;`, all `useState` /
  `useEffect` calls must be ABOVE that line.
- **TypeScript renderer + main are two separate tsconfigs.** Run BOTH
  before pushing: `./node_modules/.bin/tsc --noEmit` AND
  `./node_modules/.bin/tsc -p tsconfig.main.json --noEmit`.
- **`window.miniflow` is `any`-typed by default.** Some code uses
  `(window.miniflow as any).newMethod()` for new methods. That's fine for
  shipping; tighten with `global.d.ts` when it stabilizes.
- **Polling loops need cleanup.** Always return the unsubscribe from
  `useEffect`. Forgotten cleanup = memory leak that grows with every
  tab switch.
- **Don't change PROCESS.md lanes silently.** If you ship without
  running typecheck → it WILL break (see v1.0.29, v1.5.0). Use the
  lanes; lanes save you.

### 8.11 When in doubt — patterns to copy

| You're building | Copy from | Why |
|---|---|---|
| New list-of-things tab | `TasksTab.tsx` | Two-pane, polling, status pills |
| New scheduled workflow | `BriefingsTab.tsx` | Template card pattern, time picker |
| New config card | `BriefingsTab.MorningBriefCard` | Form grid + actions row |
| New modal | `SettingsModal.tsx` | Multi-tab modal scaffold |
| New approval card variant | `TasksTab.ApprovalRow` | Editable params + decide buttons |
| Brand-new tab | `MeetingsTab.tsx` | Header + Connect-Provider empty state |

Don't reinvent. Copy + delete what you don't need + rename.

---

## Closing

This document is a contract with future-us. If a decision here proves wrong, update the entry — but record *why* the original reasoning was insufficient. The doc gets MORE useful as we accumulate "we tried X, switched to Y because Z" notes — not less useful.

For anything not covered here, ask: which north-star principle is at stake? If you can't tell, the decision probably matters less than you think.
