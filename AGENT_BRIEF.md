# Uxie — Design Brief for AI Design Agents

> **For AI agents:** This document is a self-contained design brief.
> Read it once and you have everything you need to produce design work
> that visually matches the Uxie macOS app. Do not deviate from the
> tokens, components, or patterns in this brief unless the user
> explicitly says so. Token violations break visual consistency
> instantly — humans will notice.

*Source of truth: this brief. For deeper context: DESIGN.md in the same repo.*

---

## 1. Brand frame (30 seconds)

**Product:** Uxie — a voice-first AI agent that lives natively on macOS.
Users hold the `fn` key from any app and speak. Uxie dictates, runs
agent commands, records meetings (Granola-class), delivers a morning
brief, and runs background tasks while users work.

**Audience:** Mac power users who prefer talking to typing. Knowledge
workers — engineers, founders, designers, PMs.

**Tone:**
- Calm, considered, *not* hyped or "AI-magical."
- Spare, generous spacing — closer to Granola than to Notion.
- Macintosh-native — feels like a real Mac app, not a web dashboard.
- Voice-first, ambient — the UI is a quiet companion, not the main event.

**Comparable products** (for visual reference, NOT to copy):
- Granola (calm cream/white, sparse, meeting-focused)
- Linear (sharp, fast — but Linear is too dense for Uxie)
- Apple Mail (the Mac-native two-pane layout we mimic)

---

## 2. Design tokens — DO NOT DEVIATE

### Colors

```
Background — base
  #F3F3F1                          warm cream, never pure white
  rgba(255,255,255,0.4–0.6)        translucent insets (sidebars, cards)
  rgba(0,0,0,0.03)                 inline boxes, code blocks, muted cards

Text
  #1a1a1a                          primary (never #000 — too harsh)
  #444                             body inside dark panels
  #666                             secondary / body
  #888                             tertiary / captions / placeholder
  #3367d6                          link blue (matches macOS system link)

Status colors — uniform formula: text uses color, background uses color+0.13
  #3a8c6a   green   active / recording / success / approved
  #3367d6   blue    running / working / in-progress
  #F4A21B   amber   pending / needs human / detected-but-not-acting
  #d44a4a   red     failed / declined / destructive / error
  #7a5cd1   purple  structured / completed / premium-state
  #5b6878   gray    idle / skipped / paused

Borders
  1px solid #e5e3df                default card borders
  1px solid rgba(0,0,0,0.06)       inline box borders
  rgba(0,0,0,0.04)                 list-row separators
```

### Typography

```
Stack       -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
            (system font only — no webfonts)
Mono        ui-monospace, "SF Mono"  (only for IDs, code, transcripts)

Sizes (use ONLY these)
  22px      tab page titles            ("Meetings", "Tasks", "Briefings")
  18px      detail page titles         (meeting title, task prompt)
  15px      card titles                (section heads inside cards)
  13px      body text, list items
  12px      secondary text inside cards
  11px      captions, dates, status
  10px      section labels (always uppercase)

Section labels (special pattern):
  font-size: 11px
  text-transform: uppercase
  letter-spacing: 0.05em
  font-weight: 700
  color: #888
  margin-bottom: 8px
  used for "ACTIVITY", "TRANSCRIPT", "STRUCTURED NOTES", "RESULT", etc.
```

### Spacing

```
Grid base       4px (use multiples: 4, 8, 12, 16, 20, 24, 32)
Card padding    16px internal (12px in dense lists)
Card-to-card    12–16px vertical gap
Section gap     24px between major sections
Page padding    20–24px around main content
```

### Border radius

```
6px      buttons, input fields, small cards
8px      large cards, section containers
10–12px  modal envelopes, status pills
round    avatars, circular indicators
```

### Shadows

**Use sparingly.** Uxie's visual hierarchy is built with borders + spacing,
not shadows. The exception is the floating capsule overlay which has a
subtle elevation shadow. Everything else uses 1px borders.

---

## 3. Component patterns — exact recipes

### 3.1 Status pill (most-used primitive)

```tsx
<span style={{
  fontSize: 11,
  padding: "2px 8px",
  borderRadius: 10,
  background: color + "22",   // color@13% alpha
  color: color,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: 0.04,
}}>
  {status}
</span>
```

Rules:
- Always uppercase
- Always single word (or two short words max — "NEEDS YOU" yes,
  "WAITING FOR USER" no)
- Position: top-right of the entity's container
- Background formula: `color + "22"` (the `22` is hex alpha 0.13)

### 3.2 Primary button (filled black)

```tsx
{
  padding: "8px 14px",
  borderRadius: 6,
  border: "none",
  background: "#1a1a1a",
  color: "#fff",
  fontWeight: 600,
  cursor: "pointer",
  fontSize: 13,
}
```

### 3.3 Secondary button (outlined)

```tsx
{
  padding: "8px 14px",
  borderRadius: 6,
  border: "1px solid #ccc",
  background: "transparent",
  color: "#1a1a1a",
  cursor: "pointer",
  fontSize: 13,
}
```

### 3.4 Danger button (outlined red)

```tsx
{
  padding: "8px 14px",
  borderRadius: 6,
  border: "1px solid #d44a4a",
  background: "transparent",
  color: "#d44a4a",
  cursor: "pointer",
  fontSize: 13,
}
```

### 3.5 Chip button (small inline pill)

```tsx
{
  padding: "3px 8px",
  borderRadius: 12,
  border: "1px solid #e5e3df",
  background: "transparent",
  fontSize: 11,
  cursor: "pointer",
  color: "#666",
}
```

Used for time suggestions ("08:00", "08:30"), small filters, secondary
inline choices.

### 3.6 Input field

```tsx
{
  padding: "6px 8px",
  borderRadius: 6,
  border: "1px solid #e5e3df",
  fontFamily: "inherit",
  fontSize: 13,
  background: "rgba(255,255,255,0.8)",
}
```

### 3.7 Card

```tsx
{
  padding: 16,
  borderRadius: 8,
  border: "1px solid #e5e3df",
  background: "rgba(255,255,255,0.6)",
}
```

### 3.8 Pre / transcript box

```tsx
{
  whiteSpace: "pre-wrap",
  fontFamily: "inherit",
  fontSize: 13,
  padding: 12,
  borderRadius: 6,
  background: "rgba(0,0,0,0.04)",
  border: "1px solid rgba(0,0,0,0.06)",
  overflow: "auto",
}
```

### 3.9 Approval card (the trust mechanism)

Amber-tinted card with editable inline params + Approve/Decline buttons.

```tsx
{
  fontSize: 12,
  padding: 12,
  borderRadius: 8,
  background: "rgba(244, 162, 27, 0.08)",
  border: "1px solid rgba(244, 162, 27, 0.4)",
}
```

Anatomy (top to bottom):
1. Header row: "APPROVAL NEEDED" label (amber, uppercase) + tool name as code on the right
2. Summary line in 13px (human-readable: "Send email to john@x.com — subject: Pricing")
3. Collapsible `<details>` — inline editable form for each param (to, subject, body)
4. Button row: **Approve** (filled black) + **Decline** (outlined)

When already-resolved (history view): drop the amber tint, drop the buttons, show only a static "APPROVED" / "DECLINED" badge.

---

## 4. Layout patterns

### 4.1 Two-pane list+detail (Tasks, Meetings)

```
┌─────────────────────────────────────────────────┐
│ Aside (280-320px)        │ Main detail pane     │
│ • Header                 │ • Title              │
│ • Input (optional)       │ • Status pill        │
│ • Scrollable list:       │ • Action row         │
│   ┌──────────────────┐   │ • Sections          │
│   │ row 1            │   │   - Notes textarea   │
│   │ │ Title          │   │   - Audio player     │
│   │ │ subtitle       │   │   - Structured       │
│   │ │ [pill]         │   │   - Transcript       │
│   └──────────────────┘   │                      │
│   ┌──────────────────┐   │                      │
│   │ row 2 (selected) │   │                      │
│   └──────────────────┘   │                      │
└──────────────────────────┴──────────────────────┘
```

Aside:
- 280-320px fixed width (280 dense, 320 if rows have input forms)
- 1px right border
- `rgba(255,255,255,0.4)` translucent background
- Scrollable

Each list row:
- Padding: 10-12px vertical, 16px horizontal
- 1px bottom border at `rgba(0,0,0,0.04)`
- Selected row: `background: rgba(0,0,0,0.06)`
- Inner: title (13px, weight 600), subtitle (11px #666), pill on right

Main pane:
- Padding: 20-24px
- Scrollable
- Empty state: gray italic text, paddingTop 40
- "Select a [thing] to see details" — concise empty copy

### 4.2 Vertical stack of cards (Briefings)

```
┌───────────────────────────────────────────┐
│ Page header (22px title + 13px subtitle) │
│                                           │
│ ┌─────────────────────────────────────┐ │
│ │ Card 1 (collapsible)                │ │
│ │ • Title + status pill OR setup btn  │ │
│ │ • Description (12px #666)           │ │
│ │ • [Expanded form when active]       │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ Card 2                              │ │
│ └─────────────────────────────────────┘ │
└───────────────────────────────────────────┘
```

Stack gap: 16px. Page max-width: 720px so cards don't sprawl.

### 4.3 Tabbed modal (Settings)

```
┌─────────────────────────────────────────────┐
│ ✕  Settings · Account · Connectors · ...   │ ← header with tabs inline
├─────────────────────────────────────────────┤
│                                             │
│   Active tab body                           │
│   • Form fields                             │
│   • Action buttons                          │
│                                             │
└─────────────────────────────────────────────┘
```

Width: 720px. Tabs are buttons in the header (active tab gets bold +
black underline). Body content scrolls if it overflows.

### 4.4 Form layout inside a card

```tsx
<div style={{
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: "12px 16px",
}}>
  <label style={fieldLabel}>Field 1</label>
  <input style={input} />
  <label style={fieldLabel}>Field 2</label>
  <input style={input} />
</div>
```

`gridTemplateColumns: "auto 1fr"` is the magic — labels auto-size,
inputs take the rest. Use this instead of flexbox for any label+input
pair grid.

---

## 5. Sidebar navigation

```tsx
<nav className="sidebar">
  <div className="logo-row">
    <span className="wave-icon">〰</span>
    <span className="logo-text">Uxie</span>
  </div>

  {isListening && (
    <div className="listening-pill">
      <span className="dot" /><span>Listening</span>
    </div>
  )}

  {/* Each nav item */}
  <div className={`nav-item ${active ? "active" : ""}`} onClick={...}>
    <span className="icon">⌂</span><span>Home</span>
  </div>

  <div className="spacer" />

  <button className="sidebar-btn">
    <span>⚙</span><span>Settings</span>
  </button>
</nav>
```

Width: 200-240px. Icons are native emoji or simple unicode glyphs —
do NOT use SVG icon libraries (would add complexity for minimal gain).
Active nav-item has subtle filled background. Order: most-frequent
tabs at top, configuration at bottom, Settings always pinned bottom.

---

## 6. Brand voice — copy patterns

Brand voice in the UI:

- **Terse, action-oriented.** "Run in background" not "Submit task to background queue".
- **No marketing language.** "Connect Google" not "Unlock the power of your Gmail".
- **Lowercase except in titles + labels.** Section labels and status pills are uppercase; everything else is sentence case.
- **No exclamation marks.** Calm tone. The product doesn't celebrate at the user.
- **Empty states are direct + helpful.** "No meetings detected yet. Uxie polls your calendar every 60s." — never "Oops, nothing here!"
- **Error messages are actionable.** "Your Google connection has expired — Settings → Connectors → reconnect" — never "An error occurred".

Example UI strings used in the app (reference for tone):

| Where | String |
|---|---|
| Tasks input placeholder | "What should Uxie do in the background?" |
| Tasks submit button | "Run in background" |
| Briefings page subtitle | "Recurring agent workflows. Uxie runs these on a schedule…" |
| Empty meetings list | "No meetings detected yet. Uxie polls your calendar every 60s." |
| Empty tasks list | "No tasks yet — type a prompt above and click Run." |
| Approval card label | "APPROVAL NEEDED" |
| Status pills | "UPCOMING", "RECORDING", "TRANSCRIBED", "STRUCTURED" |

---

## 7. Anti-patterns — never do these

1. **No pure white (`#fff`) backgrounds.** Always cream `#F3F3F1` or translucent.
2. **No pure black (`#000`) text.** Always `#1a1a1a`.
3. **No drop shadows on cards** (only on the floating capsule overlay).
4. **No emoji as decorative elements** outside the sidebar icons. Especially no emoji in body copy.
5. **No more than 5 status pill colors visible on one screen** — visual noise.
6. **No mixed-case status pills.** Always uppercase + letter-spacing 0.04.
7. **No buttons with rounded "pill" radius (>16px)** for primary actions. Use 6px radius. Pill radius reads as "filter chip", not "submit".
8. **No icon-only buttons** without text labels in main UI. Acceptable in tight spaces (header close button, traffic-light dots) but otherwise label everything.
9. **No multi-line modals where content scrolls AND header tabs scroll.** Tabs stay fixed; only body scrolls.
10. **No custom webfonts.** System font only.

---

## 8. Worked example — design a "Memory" tab

A future tab Uxie might add. Use this as a reference for what
"matching the design" means.

**Brief:** Create a left-rail Memory tab where users can see things
Uxie remembers about them and their work. Each memory is a card with
the fact + when it was learned + a delete button. Top of left rail has
a search input. Empty state: "Nothing remembered yet."

**Required visual specification:**

- Tab icon in sidebar: `🧠` (native emoji) + label "Memory"
- Page header: 22px "Memory" + 13px gray subtitle line "Things Uxie remembers about you and your work"
- Two-pane layout per §4.1, aside width 280px
- Search input at top of aside: `input` style from §3.6, full-width minus 32px padding
- Memory rows: 10px vertical 16px horizontal padding, 1px bottom border `rgba(0,0,0,0.04)`. Row content: fact text in 13px (truncated to one line, ellipsis), learned-at in 11px #666 below
- Selected row background: `rgba(0,0,0,0.06)`
- Right-pane (when selected): card per §3.7 containing the full fact text, learned-at timestamp, source pill (e.g. "from meeting", "from voice command", "from email"), delete button (danger style §3.4)
- Empty state (no memories): center-aligned vertical stack, 13px gray italic "Nothing remembered yet. Uxie will start recording facts as you use it."
- Empty detail (no selection): "Select a memory to view details." Gray italic, 13px, paddingTop 40

**Copy:**
- Search placeholder: "Search memories…"
- Source pills (uppercase): "MEETING", "VOICE", "EMAIL", "MANUAL"
- Delete button: "Forget this"
- Confirm dialog: "Forget '{fact preview}'? This can't be undone."

**Interactions:**
- Debounced search (300ms) filters the aside list
- Clicking a row selects it (no double-click required)
- Delete asks for confirm, then optimistically removes from list before backend confirms

That's a complete design brief for a new tab — token-accurate, pattern-
consistent, ready for an agent to produce mockups or code.

---

## 9. The exact prompt to give the other agent

Paste this verbatim before any specific design request:

```
You are designing UI for Uxie, a voice-first AI agent for macOS.
Match the existing visual language exactly. The brief is in
AGENT_BRIEF.md (attached) — read it once, then follow it strictly.

Hard rules:
1. Use ONLY tokens from §2 of the brief. No new colors, no new sizes,
   no new spacing values.
2. Use ONLY component recipes from §3. If your design needs a primitive
   not in §3, tell me and I'll add it to the brief — don't invent.
3. Layout must match a pattern in §4 unless the user explicitly
   approves a new layout.
4. Copy must follow the brand voice in §6 — terse, lowercase, no
   exclamation marks, no marketing language.
5. NEVER violate §7's anti-patterns.

When you produce a design:
- Show me the layout structure first (ASCII or sketch)
- Then the exact style values (using tokens from §2)
- Then the copy
- Then any new interaction patterns I should confirm

If you're unsure whether something matches, ASK before producing —
"is X within the design language?" — rather than guess.

Now, here's what I need designed: [YOUR REQUEST]
```

That's the prompt template. It primes the agent to defer to the brief
instead of inventing.

---

## 10. How to iterate with the other agent

When the agent produces design output:

**Check against this rubric:**
- [ ] Every color hex matches §2 exactly (no off-by-one shades)
- [ ] Every font size matches the 8-step scale in §2
- [ ] Every spacing value is a multiple of 4
- [ ] Every border radius is 6 / 8 / 10 / 12 / round
- [ ] No shadows except where §2 allows
- [ ] Buttons match §3.2-3.5 exactly
- [ ] Status pills follow §3.1 formula
- [ ] Layout matches one of §4 patterns
- [ ] Copy follows §6 voice (terse, lowercase, no marketing)
- [ ] No anti-pattern from §7 present

If a rule is broken, point at it specifically:
> "§2 says primary text is #1a1a1a but you used #2c2c2c — fix to #1a1a1a"

This is faster than re-explaining the system. The agent learns the
brief through correction.

---

## Closing

This brief is intentionally lean. If you need deeper context — the *why*
behind decisions, anti-patterns we tried, the full component library —
read DESIGN.md (1500+ lines) and STATE.md (current state of the
codebase) in the same repo.

For most design tasks, this brief alone is enough.
