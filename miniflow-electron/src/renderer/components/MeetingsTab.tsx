import React, { useCallback, useEffect, useRef, useState } from "react";

type Meeting = {
  id: number;
  calendar_event_id: string;
  title: string;
  start_ts: number;
  end_ts: number;
  meeting_url: string;
  organizer: string;
  attendees: Array<{ email: string; name: string; response: string }>;
  status: "detected" | "recording" | "ended" | "structured" | "skipped";
  transcript: string;
  user_notes: string;
  structured_notes: string;
  created_at: number;
  updated_at: number;
};

const w = window as any;

function formatStart(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const sameTomorrow = d.toDateString() === tomorrow.toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (sameDay)        return `Today ${time}`;
  if (sameTomorrow)   return `Tomorrow ${time}`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + time;
}

function StatusPill({ status }: { status: Meeting["status"] }) {
  const map: Record<Meeting["status"], { label: string; color: string }> = {
    detected:   { label: "upcoming",   color: "#5b6878" },
    recording:  { label: "recording",  color: "#d44a4a" },
    ended:      { label: "transcribed", color: "#3a8c6a" },
    structured: { label: "structured", color: "#7a5cd1" },
    skipped:    { label: "skipped",    color: "#999" },
  };
  const s = map[status] ?? map.detected;
  return (
    <span style={{
      fontSize: 11, padding: "2px 8px", borderRadius: 10,
      background: s.color + "22", color: s.color, fontWeight: 600,
      textTransform: "uppercase", letterSpacing: 0.04,
    }}>
      {s.label}
    </span>
  );
}

export function MeetingsTab() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = (await w.miniflow.listMeetings(100)) as Meeting[];
      setMeetings(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error("[meetings] list failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const checkConnection = useCallback(async () => {
    try {
      const providers: string[] = await w.miniflow.getConnectedProviders();
      setConnected(Array.isArray(providers) && providers.includes("google"));
    } catch {
      setConnected(false);
    }
  }, []);

  // Initial load + listeners for engine pushes.
  useEffect(() => {
    checkConnection();
    refresh();
    const offRefresh   = w.miniflow.onMeetingsRefresh?.(() => refresh());
    const offDetected  = w.miniflow.onMeetingDetected?.(() => refresh());
    const offTranscript = w.miniflow.onMeetingTranscriptUpdate?.(() => refresh());
    const offConnected = w.miniflow.onOAuthConnected?.((provider: string) => {
      if (provider === "google") {
        checkConnection();
        refresh();
      }
    });
    return () => {
      offRefresh?.();
      offDetected?.();
      offTranscript?.();
      offConnected?.();
    };
  }, [refresh, checkConnection]);

  const onConnected = useCallback(() => {
    checkConnection();
    refresh();
  }, [checkConnection, refresh]);

  if (connected === null) return null;
  if (!connected) return <ConnectCalendarEmptyState onConnected={onConnected} />;

  const selected = meetings.find((m) => m.id === selectedId) ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <AutoDetectBanner />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <MeetingList
        meetings={meetings}
        selectedId={selectedId}
        onSelect={setSelectedId}
        loading={loading}
        onRefresh={refresh}
      />
      <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
        {selected
          ? <MeetingDetail meeting={selected} onChanged={refresh} />
          : <EmptyDetail />}
      </div>
      </div>
    </div>
  );
}

function AutoDetectBanner() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await (w.miniflow as any).getAutoDetectMeetings();
        setEnabled(Boolean(r?.enabled));
      } catch {
        setEnabled(false);
      }
    })();
  }, []);

  async function toggle() {
    if (enabled === null || busy) return;
    setBusy(true);
    try {
      const next = !enabled;
      await (w.miniflow as any).setAutoDetectMeetings(next);
      setEnabled(next);
    } catch (e) {
      console.error("[meetings] toggle auto-detect failed:", e);
    } finally {
      setBusy(false);
    }
  }

  if (enabled === null) return null;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 16px", borderBottom: "1px solid #e5e3df",
      background: "rgba(255,255,255,0.4)", fontSize: 12,
    }}>
      <span style={{ flex: 1 }}>
        <strong>Auto-detect meetings</strong>
        <span style={{ color: "#666", marginLeft: 8 }}>
          Watches for Slack huddles, Zoom calls, Teams meetings, and Google Meet tabs.
        </span>
      </span>
      <button
        onClick={toggle}
        disabled={busy}
        style={{
          padding: "4px 12px", borderRadius: 12, border: "1px solid #ccc",
          background: enabled ? "#1a1a1a" : "transparent",
          color: enabled ? "#fff" : "#1a1a1a",
          fontWeight: 600, fontSize: 12, cursor: busy ? "default" : "pointer",
          minWidth: 56,
        }}
      >
        {enabled ? "ON" : "OFF"}
      </button>
    </div>
  );
}

function ConnectCalendarEmptyState({ onConnected }: { onConnected: () => void }) {
  const [busy, setBusy] = useState(false);

  // OAuth completes asynchronously in a system browser — react to the
  // backend's oauth-connected event so the user sees the empty state flip
  // to the list view without having to refresh manually.
  useEffect(() => {
    const off = w.miniflow.onOAuthConnected?.((p: string) => {
      if (p === "google") onConnected();
    });
    return () => off?.();
  }, [onConnected]);

  async function connect() {
    if (busy) return;
    setBusy(true);
    try {
      await w.miniflow.startOAuth("google");
    } catch (e) {
      console.error("[meetings] startOAuth failed:", e);
      setBusy(false);
    }
  }

  return (
    <div className="home" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 40 }}>
      <h1 style={{ fontSize: 22, marginBottom: 8 }}>Meetings</h1>
      <p className="info-msg" style={{ maxWidth: 420, marginBottom: 24 }}>
        Connect your Google Calendar so Uxie can detect meetings automatically and offer to record + transcribe them in the background.
      </p>
      <button
        onClick={connect}
        disabled={busy}
        style={{
          padding: "10px 18px", borderRadius: 8, border: "none",
          background: "#1a1a1a", color: "#fff", fontWeight: 600,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? "Opening browser…" : "Connect Google Calendar"}
      </button>
      <p style={{ marginTop: 16, fontSize: 12, color: "#888" }}>
        Read-only — Uxie only sees event times, titles, and meeting URLs.
      </p>
    </div>
  );
}

function MeetingList({
  meetings, selectedId, onSelect, loading, onRefresh,
}: {
  meetings: Meeting[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <aside style={{
      width: 280, borderRight: "1px solid #e5e3df", overflow: "auto",
      background: "rgba(255,255,255,0.4)",
    }}>
      <div style={{ display: "flex", alignItems: "center", padding: "16px 16px 8px", justifyContent: "space-between" }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Meetings</div>
        <button onClick={onRefresh} disabled={loading}
                style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 12, color: "#666" }}>
          {loading ? "…" : "↻"}
        </button>
      </div>
      {meetings.length === 0 ? (
        <div style={{ padding: 16, fontSize: 13, color: "#888" }}>
          No meetings detected yet. Uxie polls your calendar every 60s.
        </div>
      ) : (
        meetings.map((m) => (
          <button
            key={m.id}
            onClick={() => onSelect(m.id)}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "10px 16px", border: "none",
              background: selectedId === m.id ? "rgba(0,0,0,0.06)" : "transparent",
              cursor: "pointer", borderBottom: "1px solid rgba(0,0,0,0.04)",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: "#1a1a1a" }}>
              {m.title || "(Untitled)"}
            </div>
            <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>
              {formatStart(m.start_ts)}
            </div>
            <StatusPill status={m.status} />
          </button>
        ))
      )}
    </aside>
  );
}

function EmptyDetail() {
  return (
    <div style={{ color: "#888", fontSize: 13, paddingTop: 40 }}>
      Select a meeting to view details, edit notes, or structure the transcript.
    </div>
  );
}

function MeetingDetail({
  meeting, onChanged,
}: {
  meeting: Meeting;
  onChanged: () => void;
}) {
  const [notes, setNotes] = useState(meeting.user_notes);
  const [structuring, setStructuring] = useState(false);
  const [structureError, setStructureError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const notesDebounce = useRef<number | null>(null);

  // Reset local state when switching meetings.
  useEffect(() => {
    setNotes(meeting.user_notes);
    setStructureError(null);
  }, [meeting.id]);

  // Persist notes to the engine 800ms after the last keystroke. Avoids
  // hammering SQLite on every character.
  useEffect(() => {
    if (notesDebounce.current) window.clearTimeout(notesDebounce.current);
    notesDebounce.current = window.setTimeout(() => {
      w.miniflow.updateMeetingNotes(meeting.id, notes).catch(() => {});
    }, 800);
    return () => { if (notesDebounce.current) window.clearTimeout(notesDebounce.current); };
  }, [notes, meeting.id]);

  async function startRecording() {
    setRecording(true);
    try {
      await w.miniflow.startMeetingRecording(meeting.id);
    } finally {
      setRecording(false);
      onChanged();
    }
  }

  async function stopRecording() {
    await w.miniflow.stopMeetingRecording(meeting.id, "");
    onChanged();
  }

  async function structure() {
    setStructureError(null);
    setStructuring(true);
    try {
      const result = await w.miniflow.structureMeeting(meeting.id);
      if (result?.error) setStructureError(result.error);
    } catch (e: any) {
      setStructureError(String(e?.message ?? e));
    } finally {
      setStructuring(false);
      onChanged();
    }
  }

  async function deleteMeeting() {
    if (!confirm(`Delete "${meeting.title}" and its transcript?`)) return;
    await w.miniflow.deleteMeeting(meeting.id);
    onChanged();
  }

  const hasTranscript = (meeting.transcript || "").trim().length > 0;
  const canStructure = hasTranscript && !structuring;

  return (
    <div>
      <header style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4 }}>
        <div>
          <h2 style={{ fontSize: 18, marginBottom: 4 }}>{meeting.title || "(Untitled)"}</h2>
          <div style={{ fontSize: 12, color: "#666" }}>
            {formatStart(meeting.start_ts)}
            {meeting.organizer && <> · organized by {meeting.organizer}</>}
          </div>
        </div>
        <StatusPill status={meeting.status} />
      </header>

      {meeting.meeting_url && (
        <a href="#" onClick={(e) => { e.preventDefault(); w.miniflow.openExternal(meeting.meeting_url); }}
           style={{ fontSize: 12, color: "#3367d6", marginTop: 4, display: "inline-block" }}>
          {meeting.meeting_url}
        </a>
      )}

      <section style={{ marginTop: 20, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {meeting.status === "detected" && (
          <>
            <button onClick={startRecording} disabled={recording}
                    style={btnPrimary}>Start recording</button>
            <button onClick={() => w.miniflow.skipMeeting(meeting.id).then(onChanged)}
                    style={btnSecondary}>Skip</button>
          </>
        )}
        {meeting.status === "recording" && (
          <button onClick={stopRecording} style={{ ...btnPrimary, background: "#d44a4a" }}>
            Stop recording
          </button>
        )}
        {(meeting.status === "ended" || meeting.status === "structured") && (
          <button onClick={structure} disabled={!canStructure} style={btnPrimary}>
            {structuring ? "Structuring…" : meeting.status === "structured" ? "Re-structure" : "Structure this meeting"}
          </button>
        )}
        <button onClick={deleteMeeting} style={btnDanger}>Delete</button>
      </section>

      {structureError && (
        <div style={{ marginTop: 12, color: "#d44a4a", fontSize: 12 }}>
          {structureError}
        </div>
      )}

      <section style={{ marginTop: 24 }}>
        <h3 style={sectionLabel}>Your notes</h3>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Type notes here while the meeting runs — Uxie uses them as a roadmap when structuring."
          style={{
            width: "100%", minHeight: 120, padding: 10, borderRadius: 6,
            border: "1px solid #e5e3df", fontFamily: "inherit", fontSize: 13,
            resize: "vertical", background: "rgba(255,255,255,0.6)",
          }}
        />
      </section>

      {(meeting.status === "structured" && meeting.structured_notes) && (
        <section style={{ marginTop: 24 }}>
          <h3 style={sectionLabel}>Structured notes</h3>
          <pre style={preBox}>{meeting.structured_notes}</pre>
        </section>
      )}

      {hasTranscript && (
        <section style={{ marginTop: 24 }}>
          <h3 style={sectionLabel}>Transcript</h3>
          <pre style={{ ...preBox, maxHeight: 320 }}>{meeting.transcript}</pre>
        </section>
      )}

      {!hasTranscript && meeting.status === "detected" && (
        <p style={{ marginTop: 24, color: "#888", fontSize: 12 }}>
          Audio capture is part of the next slice — for now, the status flow + notes are wired end-to-end so you can verify detection and the Structure button against a manually pasted transcript.
        </p>
      )}
    </div>
  );
}

const btnPrimary: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "none",
  background: "#1a1a1a", color: "#fff", fontWeight: 600, cursor: "pointer",
  fontSize: 13,
};

const btnSecondary: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "1px solid #ccc",
  background: "transparent", color: "#1a1a1a", cursor: "pointer", fontSize: 13,
};

const btnDanger: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 6, border: "1px solid #d44a4a",
  background: "transparent", color: "#d44a4a", cursor: "pointer", fontSize: 13,
};

const sectionLabel: React.CSSProperties = {
  fontSize: 11, textTransform: "uppercase", letterSpacing: 0.05,
  color: "#888", fontWeight: 700, marginBottom: 8,
};

const preBox: React.CSSProperties = {
  whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13,
  padding: 12, borderRadius: 6, background: "rgba(0,0,0,0.04)",
  border: "1px solid rgba(0,0,0,0.06)", overflow: "auto",
};
