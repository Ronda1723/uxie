// OverlayWidget — single floating capsule that renders every state from
// docs/widgets.md (dictating, transcribing, thinking, acting, done, error,
// review). Mode is pushed in over the `widget:state` IPC channel; the
// component reports its rendered height so main can resize the window.

import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

// ── Mode types — mirror src/main/widgetState.ts ─────────────────────────────

type Mode =
  | { kind: "hidden" }
  | { kind: "dictating"; partial?: string; startedAt: number }
  | { kind: "transcribing"; text: string }
  | { kind: "thinking"; cleaned?: string; routingTo?: string }
  | { kind: "acting"; app?: string; action?: string }
  | { kind: "done"; summary: string }
  | { kind: "error"; message: string }
  | {
      kind: "review";
      tool: string;
      summary: string;
      params: Record<string, unknown>;
    };

const TOOL_ICONS: Record<string, string> = {
  gmail_send: "✉️", gmail_reply: "↩️", gmail_send_email: "✉️", gmail_draft: "📝",
  create_calendar_event: "📅", create_calendar_event_local: "📅",
  slack_send_message: "💬", slack_post: "💬",
  delete_file: "🗑️",
  linear_create_issue: "🔷", notion_create_page: "📄",
};
const TOOL_LABELS: Record<string, string> = {
  gmail_send: "Send Email", gmail_reply: "Reply to Email", gmail_draft: "Save Draft",
  create_calendar_event: "Create Event", create_calendar_event_local: "Create Event",
  slack_send_message: "Send Slack Message", slack_post: "Post to Slack",
  delete_file: "Delete File",
  linear_create_issue: "Create Linear Issue", notion_create_page: "Create Notion Page",
};

// ── Top-level component ─────────────────────────────────────────────────────

export function OverlayWidget() {
  const [mode, setMode] = useState<Mode>({ kind: "hidden" });
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Subscribe to mode pushes from main.
  useEffect(() => {
    const off = (window.miniflow as any).onWidgetState?.((m: Mode) => setMode(m));
    return () => off?.();
  }, []);

  // After every render, report our card's natural height so the BrowserWindow
  // can resize without leaving an empty band of transparent pixels.
  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const h = el.offsetHeight;
    (window.miniflow as any).reportWidgetSize?.(h + 16); // +16 for the dock gap
  });

  if (mode.kind === "hidden") {
    // Render nothing visible but still report 56 so we have a sensible
    // fallback size if main pre-creates the window.
    return <div style={{ height: 0 }} />;
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0,
        display: "flex", justifyContent: "center", alignItems: "flex-end",
        padding: "0 16px 16px 16px",
        pointerEvents: "none",
      }}
    >
      <div
        ref={cardRef}
        style={{
          pointerEvents: mode.kind === "review" ? "auto" : "none",
          background: "rgba(20, 15, 10, 0.88)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 22,
          width: "100%",
          maxWidth: 448,
          boxShadow: "0 12px 36px rgba(0,0,0,0.55)",
          color: "#fff",
          fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif",
          padding: "14px 16px",
          transition: "all 240ms cubic-bezier(0.2, 0.8, 0.25, 1.0)",
        }}
      >
        <Body mode={mode} />
      </div>
    </div>
  );
}

// ── Body switch ─────────────────────────────────────────────────────────────

function Body({ mode }: { mode: Mode }) {
  switch (mode.kind) {
    case "dictating":
      return <Dictating startedAt={mode.startedAt} partial={mode.partial} />;
    case "transcribing":
      return <Transcribing text={mode.text} />;
    case "thinking":
      return <Thinking cleaned={mode.cleaned} routingTo={mode.routingTo} />;
    case "acting":
      return <Acting app={mode.app} action={mode.action} />;
    case "done":
      return <Done summary={mode.summary} />;
    case "error":
      return <ErrorState message={mode.message} />;
    case "review":
      return <Review tool={mode.tool} summary={mode.summary} params={mode.params} />;
    default:
      return null;
  }
}

// ── Dictating ───────────────────────────────────────────────────────────────

function Dictating({ startedAt, partial }: { startedAt: number; partial?: string }) {
  const [seconds, setSeconds] = useState(0);
  const [amps, setAmps] = useState<number[]>(() => Array(22).fill(0.05));

  // mm:ss timer.
  useEffect(() => {
    const id = setInterval(() => {
      setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 200);
    return () => clearInterval(id);
  }, [startedAt]);

  // Amplitude waveform. Until we wire real mic RMS from Python, drive the
  // bars with a smoothed-noise process so they feel alive instead of static.
  // Each bar gets its own random walk seeded by sin() so the row breathes.
  useEffect(() => {
    let prev = amps.slice();
    const id = setInterval(() => {
      // Shift left, push a new "live" amplitude on the right.
      const next = prev.slice(1);
      const t = Date.now() / 1000;
      const base = 0.45 + 0.35 * Math.sin(t * 4.2) * Math.sin(t * 1.7);
      const jitter = (Math.random() - 0.5) * 0.4;
      const amp = Math.max(0.05, Math.min(1, base + jitter));
      next.push(amp);
      prev = next;
      setAmps(next);
    }, 90);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startedAt]);

  return (
    <Row>
      <RecDot />
      <Waveform amps={amps} />
      <Timer seconds={seconds} />
    </Row>
  );
}

function RecDot() {
  return (
    <div
      style={{
        width: 10, height: 10, borderRadius: "50%",
        background: "#ed5048",
        boxShadow: "0 0 8px rgba(237,80,72,0.65)",
        animation: "uxiePulse 1.4s ease-in-out infinite",
        flexShrink: 0,
      }}
    />
  );
}

function Waveform({ amps }: { amps: number[] }) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "stretch",
        gap: 3,
        height: 28,
      }}
    >
      {amps.map((a, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.max(8, Math.round(a * 100))}%`,
            background: "rgba(255,255,255,0.92)",
            borderRadius: 999,
            transition: "height 110ms ease-out",
          }}
        />
      ))}
    </div>
  );
}

function Timer({ seconds }: { seconds: number }) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return (
    <span
      style={{
        fontFamily: "'SF Mono', ui-monospace, monospace",
        fontSize: 13,
        fontVariantNumeric: "tabular-nums",
        color: "rgba(255,255,255,0.9)",
        flexShrink: 0,
      }}
    >
      {m}:{s.toString().padStart(2, "0")}
    </span>
  );
}

// ── Transcribing / Thinking / Acting / Done / Error ─────────────────────────

function Transcribing({ text }: { text: string }) {
  return (
    <Row>
      <AccentDot color="#7aa7ff" />
      <Eyebrow>Transcribing</Eyebrow>
      <BodyText>{text || "…"}</BodyText>
    </Row>
  );
}

function Thinking({ cleaned, routingTo }: { cleaned?: string; routingTo?: string }) {
  return (
    <Row>
      <Spinner />
      <Eyebrow>{routingTo ? `Routing to ${routingTo}` : "Routing"}</Eyebrow>
      <BodyText>{cleaned || "…"}</BodyText>
    </Row>
  );
}

function Acting({ app, action }: { app?: string; action?: string }) {
  const label = action || (app ? `${app} · running` : "Running");
  return (
    <Row>
      <Spinner />
      <Eyebrow>Running</Eyebrow>
      <BodyText>{label}</BodyText>
    </Row>
  );
}

function Done({ summary }: { summary: string }) {
  return (
    <Row>
      <CheckDot />
      <EyebrowGreen>Done</EyebrowGreen>
      <BodyText>{summary}</BodyText>
    </Row>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <Row>
      <AccentDot color="#ff5c5c" />
      <EyebrowAmber>Error</EyebrowAmber>
      <BodyText>{message}</BodyText>
    </Row>
  );
}

// ── Review (approval card — fields are editable inline before Send) ─────────

/** Tool kind → ordered list of [paramKey, label, kind] tuples for the form.
 *  Falls through to the generic case for tools we haven't laid out yet. */
function fieldSpec(tool: string, params: Record<string, unknown>): Array<{ key: string; label: string; kind: "line" | "block" | "mono" }> {
  if (tool.startsWith("gmail")) {
    return [
      { key: "to",      label: "To",      kind: "mono" },
      { key: "subject", label: "Subject", kind: "line" },
      { key: "body",    label: "Body",    kind: "block" },
    ];
  }
  if (tool.startsWith("create_calendar")) {
    return [
      { key: params.title !== undefined ? "title" : "summary", label: "Title", kind: "line" },
      { key: params.start !== undefined ? "start" : "start_time", label: "Start", kind: "mono" },
      { key: params.end   !== undefined ? "end"   : "end_time",   label: "End",   kind: "mono" },
    ];
  }
  if (tool.startsWith("slack")) {
    return [
      { key: "channel", label: "Channel", kind: "mono" },
      { key: params.text !== undefined ? "text" : "message", label: "Message", kind: "block" },
    ];
  }
  // Generic fallback — every string/number param becomes an editable line.
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k]) => ({ key: k, label: k, kind: "line" as const }));
}

function Review({ tool, summary, params }: { tool: string; summary: string; params: Record<string, unknown> }) {
  // Local copy of params the user can edit inline. Initialised from the
  // agent's proposed params; flushed back via sendApproval(true, edited).
  const [edited, setEdited] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === null || v === undefined) continue;
      out[k] = typeof v === "string" ? v : String(v);
    }
    return out;
  });

  // If a *new* approval request comes in (different tool/params), reset.
  useEffect(() => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === null || v === undefined) continue;
      out[k] = typeof v === "string" ? v : String(v);
    }
    setEdited(out);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, JSON.stringify(params)]);

  function respond(approved: boolean) {
    // Only send the edited diff back — keys whose value differs from the
    // original. Saves bandwidth and avoids accidentally clobbering nested
    // structures the user can't even see in the UI.
    let diff: Record<string, unknown> | undefined;
    if (approved) {
      diff = {};
      for (const [k, v] of Object.entries(edited)) {
        const orig = params[k];
        const origStr = orig == null ? "" : typeof orig === "string" ? orig : String(orig);
        if (v !== origStr) diff[k] = v;
      }
      if (Object.keys(diff).length === 0) diff = undefined;
    }
    (window.miniflow as any).sendApproval?.(approved, diff);
  }

  const icon = TOOL_ICONS[tool] ?? "⚡";
  const label = TOOL_LABELS[tool] ?? tool;
  const spec = fieldSpec(tool, params);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{label}</span>
        <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#ff9f0a" }} />
      </div>
      <div style={{ height: 1, background: "rgba(255,255,255,0.07)" }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {spec.map(({ key, label: l, kind }) => (
          <EditableField
            key={key}
            label={l}
            value={edited[key] ?? ""}
            kind={kind}
            onChange={(v) => setEdited((s) => ({ ...s, [key]: v }))}
          />
        ))}
        {!spec.length && summary && (
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", lineHeight: 1.4 }}>
            {summary}
          </span>
        )}
      </div>
      <div style={{ height: 1, background: "rgba(255,255,255,0.07)" }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => respond(true)}
          style={{
            flex: 1, padding: "8px 0", borderRadius: 10,
            background: "#0a84ff", border: "none",
            color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}
        >Send ↑</button>
        <button
          onClick={() => respond(false)}
          style={{
            flex: 1, padding: "8px 0", borderRadius: 10,
            background: "rgba(255,255,255,0.07)",
            border: "1px solid rgba(255,255,255,0.1)",
            color: "rgba(255,255,255,0.6)", fontSize: 13, fontWeight: 500, cursor: "pointer",
          }}
        >Cancel</button>
      </div>
    </div>
  );
}

/** Editable single-line or multi-line field inside the review card. */
function EditableField({
  label, value, kind, onChange,
}: {
  label: string;
  value: string;
  kind: "line" | "block" | "mono";
  onChange: (v: string) => void;
}) {
  const sharedStyle: React.CSSProperties = {
    width: "100%",
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 8,
    padding: "6px 10px",
    color: "rgba(255,255,255,0.92)",
    fontSize: 12,
    lineHeight: 1.4,
    fontFamily: kind === "mono" ? "'SF Mono', ui-monospace, monospace" : "inherit",
    outline: "none",
    boxSizing: "border-box",
    resize: kind === "block" ? "vertical" : "none",
    pointerEvents: "auto",
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{
        fontSize: 10, fontWeight: 700, color: "rgba(255,255,255,0.4)",
        textTransform: "uppercase", letterSpacing: "0.07em",
      }}>
        {label}
      </span>
      {kind === "block" ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={Math.min(8, Math.max(2, value.split("\n").length))}
          style={sharedStyle}
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={sharedStyle}
        />
      )}
    </div>
  );
}

// ── Tiny shared atoms ───────────────────────────────────────────────────────

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto auto 1fr auto",
        alignItems: "center",
        gap: 12,
        minHeight: 32,
      }}
    >
      {children}
    </div>
  );
}

function AccentDot({ color }: { color: string }) {
  return <div style={{ width: 10, height: 10, borderRadius: "50%", background: color, flexShrink: 0 }} />;
}

function CheckDot() {
  return (
    <div
      style={{
        width: 18, height: 18, borderRadius: "50%",
        background: "rgba(52, 199, 89, 0.25)",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <span style={{ fontSize: 11, color: "#34c759", fontWeight: 700 }}>✓</span>
    </div>
  );
}

function Spinner() {
  return (
    <div
      style={{
        width: 14, height: 14,
        border: "2px solid rgba(255,255,255,0.18)",
        borderTopColor: "rgba(255,255,255,0.85)",
        borderRadius: "50%",
        animation: "uxieSpin 0.85s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.55)",
      textTransform: "uppercase", letterSpacing: "0.08em", whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

function EyebrowGreen({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color: "#34c759",
      textTransform: "uppercase", letterSpacing: "0.08em", whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

function EyebrowAmber({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color: "#ff9f0a",
      textTransform: "uppercase", letterSpacing: "0.08em", whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

function BodyText({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 13, color: "rgba(255,255,255,0.92)",
      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      minWidth: 0,
    }}>{children}</span>
  );
}
