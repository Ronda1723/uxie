import React, { useEffect, useState } from "react";

interface ApprovalEvent {
  tool: string;
  summary: string;
  params: Record<string, unknown>;
}

const TOOL_ICONS: Record<string, string> = {
  gmail_send: "✉️", gmail_reply: "↩️", gmail_send_email: "✉️",
  create_calendar_event: "📅",
  slack_send_message: "💬", slack_context_reply: "💬", slack_post: "💬",
  delete_file: "🗑️", move_file: "📁",
  linear_create_issue: "🔷", notion_create_page: "📄",
  github_create_pr: "🔀", github_create_issue: "🐛",
  jira_create_issue: "🎯",
};

const TOOL_LABELS: Record<string, string> = {
  gmail_send: "Send Email", gmail_reply: "Reply to Email", gmail_send_email: "Send Email",
  create_calendar_event: "Create Calendar Event",
  slack_send_message: "Send Slack Message", slack_context_reply: "Reply on Slack", slack_post: "Post to Slack",
  delete_file: "Delete File", move_file: "Move File",
  linear_create_issue: "Create Linear Issue", notion_create_page: "Create Notion Page",
  github_create_pr: "Create Pull Request", github_create_issue: "Create Issue",
  jira_create_issue: "Create Jira Issue",
};

function s(v: unknown): string {
  if (!v) return "";
  if (typeof v === "string") return v;
  return String(v);
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  if (!value) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: "rgba(255,255,255,0.35)",
                     textTransform: "uppercase", letterSpacing: "0.07em" }}>
        {label}
      </span>
      <span style={{
        fontSize: 12, color: "rgba(255,255,255,0.85)", lineHeight: 1.4,
        fontFamily: mono ? "'SF Mono', monospace" : "inherit",
        wordBreak: "break-word",
        maxHeight: 72, overflow: "hidden",
        display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical",
      }}>
        {value}
      </span>
    </div>
  );
}

function DetailCard({ tool, params }: { tool: string; params: Record<string, unknown> }) {
  // Email
  if (tool === "gmail_send" || tool === "gmail_send_email" || tool === "gmail_reply") {
    return (
      <>
        <Field label="To" value={s(params.to)} mono />
        {params.cc && <Field label="CC" value={s(params.cc)} mono />}
        <Field label="Subject" value={s(params.subject)} />
        <Field label="Body" value={s(params.body)} />
      </>
    );
  }
  // Calendar
  if (tool === "create_calendar_event") {
    const attendees = Array.isArray(params.attendees)
      ? params.attendees.map((a: any) => (typeof a === "string" ? a : a?.email ?? "")).join(", ")
      : s(params.attendees);
    return (
      <>
        <Field label="Title" value={s(params.title || params.summary)} />
        <Field label="Start" value={s(params.start || params.start_time)} />
        <Field label="End" value={s(params.end || params.end_time)} />
        {attendees && <Field label="Attendees" value={attendees} mono />}
        {params.description && <Field label="Description" value={s(params.description)} />}
      </>
    );
  }
  // Slack
  if (tool.startsWith("slack")) {
    return (
      <>
        <Field label="Channel" value={s(params.channel)} />
        <Field label="Message" value={s(params.text || params.message)} />
      </>
    );
  }
  // Generic fallback: show all non-empty params
  return (
    <>
      {Object.entries(params).map(([k, v]) =>
        v ? <Field key={k} label={k} value={s(v)} /> : null
      )}
    </>
  );
}

export function OverlayWidget() {
  const [event, setEvent] = useState<ApprovalEvent | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const off = (window.miniflow as any).onApprovalNeeded?.((e: ApprovalEvent) => {
      setEvent(e);
      setVisible(true);
    });
    return () => off?.();
  }, []);

  function respond(approved: boolean) {
    (window.miniflow as any).sendApproval?.(approved);
    setVisible(false);
    setTimeout(() => setEvent(null), 300);
  }

  const icon = event ? (TOOL_ICONS[event.tool] ?? "⚡") : "⚡";
  const label = event ? (TOOL_LABELS[event.tool] ?? event.tool) : "";

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0,
      display: "flex", justifyContent: "center",
      padding: "12px 16px",
      pointerEvents: "none",
    }}>
      <div style={{
        pointerEvents: "auto",
        background: "rgba(16, 16, 22, 0.94)",
        backdropFilter: "blur(28px)",
        WebkitBackdropFilter: "blur(28px)",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 18,
        padding: "14px 16px",
        width: 380,
        boxShadow: "0 12px 40px rgba(0,0,0,0.6)",
        transform: visible ? "translateY(0)" : "translateY(-115%)",
        opacity: visible ? 1 : 0,
        transition: "transform 0.3s cubic-bezier(0.34,1.56,0.64,1), opacity 0.2s ease",
        display: "flex",
        flexDirection: "column" as const,
        gap: 10,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif",
      }}>

        {/* Header row */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#fff", flex: 1 }}>{label}</span>
          <div style={{
            width: 7, height: 7, borderRadius: "50%",
            background: "#ff9f0a", flexShrink: 0,
          }} />
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "0 -4px" }} />

        {/* Detail fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {event && <DetailCard tool={event.tool} params={event.params} />}
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "0 -4px" }} />

        {/* Buttons */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => respond(true)}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 10,
              background: "#0a84ff", border: "none",
              color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit",
              letterSpacing: "0.01em",
            }}
          >
            Send ↑
          </button>
          <button
            onClick={() => respond(false)}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 10,
              background: "rgba(255,255,255,0.07)",
              border: "1px solid rgba(255,255,255,0.1)",
              color: "rgba(255,255,255,0.6)", fontSize: 13, fontWeight: 500,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            Cancel
          </button>
        </div>

      </div>
    </div>
  );
}
