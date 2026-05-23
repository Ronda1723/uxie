import React, { useCallback, useEffect, useState } from "react";

type Schedule = {
  id: string;
  kind: "morning_brief" | string;
  enabled: boolean;
  run_time_local: string;   // "HH:MM"
  timezone: string;
  delivery: { notification?: boolean; email?: boolean };
  config: Record<string, unknown>;
  last_fired_at: string | null;
  last_task_id: string | null;
  created_at: string;
};

const w = window as any;

const COMMON_TIMES = ["07:00", "07:30", "08:00", "08:30", "09:00", "09:30", "10:00"];

function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function formatLastFired(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function BriefingsTab() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastBrief, setLastBrief] = useState<{ id: string; md: string; firedAt: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await w.miniflow.listSchedules();
      const list: Schedule[] = Array.isArray(r?.scheduled_tasks) ? r.scheduled_tasks : [];
      setSchedules(list);

      // If a brief has fired and we haven't shown it yet, fetch its markdown.
      const morning = list.find((s) => s.kind === "morning_brief" && s.last_task_id);
      if (morning && morning.last_task_id) {
        try {
          const t = await w.miniflow.getTask(morning.last_task_id);
          if (t?.result_md) {
            setLastBrief({
              id: morning.last_task_id,
              md: t.result_md,
              firedAt: morning.last_fired_at || "",
            });
          }
        } catch (e) {
          console.error("[briefings] fetch last brief failed:", e);
        }
      }
    } catch (e) {
      console.error("[briefings] list failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // Light polling — once a minute is enough since briefings are
    // scheduled, not interactive.
    const interval = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const morning = schedules.find((s) => s.kind === "morning_brief") ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "auto" }}>
      <div style={{ padding: "20px 24px", maxWidth: 720 }}>
        <h1 style={{ fontSize: 22, marginBottom: 4 }}>Briefings</h1>
        <p className="info-msg" style={{ marginBottom: 24, fontSize: 13, color: "#666" }}>
          Uxie wakes up before you do, scans your inbox + calendar, and delivers a one-screen brief — as a macOS notification and an email.
        </p>

        <MorningBriefCard schedule={morning} onChanged={refresh} />

        {lastBrief && (
          <section style={{ marginTop: 32 }}>
            <h2 style={{ fontSize: 16, marginBottom: 8 }}>Most recent brief</h2>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 8 }}>
              {formatLastFired(lastBrief.firedAt)}
            </div>
            <pre style={preBox}>{lastBrief.md}</pre>
          </section>
        )}

        {loading && schedules.length === 0 && (
          <div style={{ marginTop: 24, fontSize: 12, color: "#888" }}>Loading…</div>
        )}
      </div>
    </div>
  );
}

function MorningBriefCard({
  schedule, onChanged,
}: {
  schedule: Schedule | null;
  onChanged: () => void;
}) {
  const [time, setTime] = useState(schedule?.run_time_local ?? "08:00");
  const [tz, setTz] = useState(schedule?.timezone ?? detectTimezone());
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [emailEnabled, setEmailEnabled] = useState(schedule?.delivery?.email ?? true);
  const [notifyEnabled, setNotifyEnabled] = useState(schedule?.delivery?.notification ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync local state when the row changes from polling.
  useEffect(() => {
    if (!schedule) return;
    setTime(schedule.run_time_local);
    setTz(schedule.timezone);
    setEnabled(schedule.enabled);
    setEmailEnabled(schedule.delivery?.email ?? true);
    setNotifyEnabled(schedule.delivery?.notification ?? true);
  }, [schedule?.id, schedule?.run_time_local, schedule?.timezone, schedule?.enabled,
      schedule?.delivery?.email, schedule?.delivery?.notification]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const delivery = { email: emailEnabled, notification: notifyEnabled };
      if (schedule) {
        await w.miniflow.patchSchedule(schedule.id, {
          run_time_local: time, timezone: tz, enabled, delivery,
        });
      } else {
        const r = await w.miniflow.createSchedule({
          kind: "morning_brief",
          run_time_local: time, timezone: tz, enabled, delivery,
        });
        if (r?.error) setError(r.error);
      }
      onChanged();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function fireNow() {
    if (!schedule) return;
    setBusy(true);
    setError(null);
    try {
      await w.miniflow.fireSchedule(schedule.id);
      // Give the cron a moment to start, then refresh.
      window.setTimeout(onChanged, 1500);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!schedule) return;
    if (!confirm("Delete the morning brief schedule?")) return;
    setBusy(true);
    try {
      await w.miniflow.deleteSchedule(schedule.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>Morning Brief</h2>
        <label style={{ fontSize: 12, color: "#666", display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>Enabled</span>
        </label>
      </div>
      <p style={{ marginTop: 8, fontSize: 12, color: "#666", lineHeight: 1.5 }}>
        Every morning, Uxie scans your calendar + unread Gmail and synthesizes a one-screen Markdown brief — today's schedule, inbox highlights, and anything you should know about.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "12px 16px", marginTop: 16 }}>
        <label style={fieldLabel}>Send at</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            style={{ ...input, width: 110 }}
          />
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {COMMON_TIMES.map((t) => (
              <button key={t} onClick={() => setTime(t)} style={chipBtn}>{t}</button>
            ))}
          </div>
        </div>

        <label style={fieldLabel}>Timezone</label>
        <input value={tz} onChange={(e) => setTz(e.target.value)} style={input} placeholder="e.g. Asia/Kolkata" />

        <label style={fieldLabel}>Deliver as</label>
        <div style={{ display: "flex", gap: 16 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={notifyEnabled} onChange={(e) => setNotifyEnabled(e.target.checked)} />
            macOS notification
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={emailEnabled} onChange={(e) => setEmailEnabled(e.target.checked)} />
            Email to your Uxie account
          </label>
        </div>
      </div>

      <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={save} disabled={busy} style={btnPrimary}>
          {schedule ? "Save changes" : "Set up morning brief"}
        </button>
        {schedule && (
          <>
            <button onClick={fireNow} disabled={busy} style={btnSecondary}>Send brief now</button>
            <button onClick={remove} disabled={busy} style={btnDanger}>Delete</button>
          </>
        )}
        {schedule && (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "#888" }}>
            Last fired: {formatLastFired(schedule.last_fired_at)}
          </span>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 12, color: "#d44a4a", fontSize: 12 }}>{error}</div>
      )}
    </div>
  );
}

const card: React.CSSProperties = {
  padding: 16, borderRadius: 8, border: "1px solid #e5e3df",
  background: "rgba(255,255,255,0.6)",
};

const fieldLabel: React.CSSProperties = {
  fontSize: 12, color: "#666", paddingTop: 7,
};

const input: React.CSSProperties = {
  padding: "6px 8px", borderRadius: 6, border: "1px solid #e5e3df",
  fontFamily: "inherit", fontSize: 13, background: "rgba(255,255,255,0.8)",
};

const chipBtn: React.CSSProperties = {
  padding: "3px 8px", borderRadius: 12, border: "1px solid #e5e3df",
  background: "transparent", fontSize: 11, cursor: "pointer", color: "#666",
};

const btnPrimary: React.CSSProperties = {
  padding: "7px 14px", borderRadius: 6, border: "none",
  background: "#1a1a1a", color: "#fff", fontWeight: 600, cursor: "pointer", fontSize: 13,
};

const btnSecondary: React.CSSProperties = {
  padding: "7px 12px", borderRadius: 6, border: "1px solid #ccc",
  background: "transparent", color: "#1a1a1a", cursor: "pointer", fontSize: 13,
};

const btnDanger: React.CSSProperties = {
  padding: "7px 12px", borderRadius: 6, border: "1px solid #d44a4a",
  background: "transparent", color: "#d44a4a", cursor: "pointer", fontSize: 13,
};

const preBox: React.CSSProperties = {
  whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13, lineHeight: 1.5,
  padding: 16, borderRadius: 8, background: "rgba(0,0,0,0.03)",
  border: "1px solid rgba(0,0,0,0.06)", overflow: "auto",
};
