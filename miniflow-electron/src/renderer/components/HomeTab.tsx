import React, { useEffect, useRef, useState, useCallback } from "react";

interface Props {
  userName: string;
  isListening: boolean;
  isProcessing: boolean;
  captureMode?: "dictation" | "command";
}

interface HistoryEntry {
  id?: string;
  timestamp: string;
  transcript: string;
  entry_type: string;
  actions?: { action: string; success: boolean; message: string }[];
  success: boolean;
}

interface DebugEntry {
  time: string;
  type: "stt" | "llm" | "inject" | "error";
  app: string;
  text: string;
  success?: boolean;
}

export function HomeTab({ userName, isListening, isProcessing, captureMode = "dictation" }: Props) {
  const [commandText, setCommandText] = useState("");
  const [lastTranscript, setLastTranscript] = useState<string>("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [debugLog, setDebugLog] = useState<DebugEntry[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const addDebug = useCallback((entry: DebugEntry) => {
    setDebugLog((prev) => [...prev.slice(-49), entry]);
  }, []);

  async function refreshHistory() {
    try {
      const raw = (await window.miniflow.getHistory()) as HistoryEntry[];
      setHistory(Array.isArray(raw) ? raw : []);
    } catch { /* backend may not be ready */ }
  }

  useEffect(() => { refreshHistory(); }, []);

  useEffect(() => {
    // Streaming chunks arrive as the LLM generates them — accumulate into the
    // preview so the user sees the corrected text grow in real time.
    let streaming = "";
    const offChunk = (window.miniflow as any).onDictationChunk?.((chunk: string) => {
      streaming += chunk;
      setLastTranscript(streaming);
    });
    const offTx = (window.miniflow as any).onTranscription?.(
      (p: { transcript: string; is_final: boolean; is_session?: boolean }) => {
        if (!p?.transcript || !p.is_session) return;
        // Session-final snapshot from the raw Waves transcript (command mode).
        setLastTranscript(p.transcript);
        streaming = "";
        setTimeout(refreshHistory, 1500);
      }
    );
    const offErr = (window.miniflow as any).onTranscriptionError?.(
      (msg: string) => setError(msg)
    );
    const offAct = window.miniflow.onAction((a: any) => {
      if (a?.action === "dictation-final" && a?.message) {
        setLastTranscript(a.message);
        streaming = "";
      }
      if (a?.action === "llm-error") {
        addDebug({ time: now(), type: "error", app: "engine", text: a.message, success: false });
      }
      refreshHistory();
    });
    const offDbg = (window.miniflow as any).onDebugEvent?.((e: any) => {
      addDebug({
        time: now(),
        type: e.type as DebugEntry["type"],
        app: appLabel(e.app),
        text: e.text,
        success: e.success,
      });
    });
    return () => { offChunk?.(); offTx?.(); offErr?.(); offAct?.(); offDbg?.(); };
  }, []);

  async function sendCommand() {
    const text = commandText.trim();
    if (!text) return;
    setCommandText("");
    setError(null);
    try { await (window.miniflow as any).executeCommand(text); }
    catch (e: any) { setError(e?.message ?? String(e)); }
    refreshHistory();
  }

  const greeting = userName ? `Welcome back, ${userName}` : "Welcome back";

  return (
    <div className="home">
      <h1>{greeting}</h1>

      {/* Stats */}
      <div className="section stats">
        <StatCell icon="🔥" value="0" label="day streak" />
        <StatCell icon="🚀" value={String(history.length)} label="commands" />
        <StatCell icon="🏆" value="—" label="WPM" />
      </div>

      {/* Fn card — the listening indicator */}
      <div className={`section fn-card ${isListening ? "listening" : ""}`}>
        <div className="inner">
          <div className="left">
            {isListening ? (
              <>
                <div className="hint" style={{ fontWeight: 500 }}>
                  Listening…
                  <span className="chip-tag" style={{
                    marginLeft: 8,
                    background: captureMode === "command" ? "var(--accent-brown)" : "var(--fn-card-border)",
                    color: captureMode === "command" ? "#fff" : "var(--accent-brown)",
                  }}>
                    {captureMode === "command" ? "command mode" : "dictation"}
                  </span>
                </div>
              </>
            ) : isProcessing ? (
              <div className="hint" style={{ color: "var(--accent-brown)", fontWeight: 500 }}>Processing…</div>
            ) : (
              <>
                <div className="hint">
                  <span>Hold</span>
                  <span className="fn-kbd">fn</span>
                  <span>to start dictating</span>
                </div>
                <div className="desc">
                  Speak naturally — Uxie transcribes and executes your voice commands in any app.
                </div>
              </>
            )}
          </div>
          <div className={`mic-btn ${isListening ? "listening" : ""}`}>
            {isListening ? "■" : "🎙"}
          </div>
        </div>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 8 }}>{error}</div>}

      {/* Last transcript preview (read-only) — shows what was heard + typed.
          Kept separate from the command bar so the helper's synthetic typing
          doesn't collide with React's controlled input value. */}
      {lastTranscript && (
        <div className="section" style={{
          background: "var(--fn-card-bg)", border: "1px solid var(--fn-card-border)",
          borderRadius: 10, padding: "10px 14px",
        }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
                        textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Last transcript
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.4 }}>{lastTranscript}</div>
        </div>
      )}

      {/* Command bar — for manual typed commands only. Dictation never writes here. */}
      <div className="section command-bar">
        <span className="mag">🔍</span>
        <input
          ref={inputRef}
          type="text"
          placeholder={isListening ? "Listening…" : "Type a command or ask AI…"}
          value={commandText}
          onChange={(e) => setCommandText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") sendCommand(); }}
        />
        {commandText && !isListening && (
          <button className="execute" onClick={sendCommand}>
            <span>➤</span><span>Execute</span>
          </button>
        )}
      </div>

      {/* Debug log */}
      <DebugPanel entries={debugLog} onClear={() => setDebugLog([])} />

      {/* History */}
      {history.length > 0 && <HistoryGrouped entries={history} onRefresh={refreshHistory} />}
    </div>
  );
}

function StatCell({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <div className="cell">
      <span className="icon">{icon}</span>
      <div>
        <div className="value">{value}</div>
        <div className="label">{label}</div>
      </div>
    </div>
  );
}

function HistoryGrouped({ entries, onRefresh }: { entries: HistoryEntry[]; onRefresh: () => void }) {
  const groups = groupByDay(entries);
  const keys = Object.keys(groups).sort((a, b) => groupOrder(a) - groupOrder(b));

  async function clearAll() {
    if (!confirm("Clear all history?")) return;
    await window.miniflow.clearHistory();
    onRefresh();
  }

  return (
    <div className="section">
      {keys.map((k) => (
        <div className="history-group" key={k}>
          <div className="date-header">
            <span>{k.toUpperCase()}</span>
            {k === "Today" && <button className="clear-link" onClick={clearAll}>Clear all</button>}
          </div>
          <div className="history-table">
            {groups[k].slice(0, 20).map((e, i) => (
              <div className="history-row" key={i}>
                <span className="time">{formatTime(e.timestamp)}</span>
                <span className="tx">{e.transcript}</span>
                <span className={e.success ? "ok" : "fail"}>{e.success ? "✓" : "✗"}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Debug panel ───────────────────────────────────────────────────────────────

const TYPE_META: Record<DebugEntry["type"], { label: string; color: string }> = {
  stt:    { label: "STT",    color: "#3b82f6" },
  llm:    { label: "LLM",    color: "#10b981" },
  inject: { label: "INJECT", color: "#8b5cf6" },
  error:  { label: "ERR",    color: "#ef4444" },
};

function DebugPanel({ entries, onClear }: { entries: DebugEntry[]; onClear: () => void }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className="section" style={{
      background: "#0d1117", border: "1px solid #30363d",
      borderRadius: 10, padding: "10px 14px", fontFamily: "monospace",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Debug log
        </span>
        <button
          onClick={onClear}
          style={{ fontSize: 10, color: "#8b949e", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          clear
        </button>
      </div>
      <div style={{ maxHeight: 180, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
        {entries.length === 0 && (
          <div style={{ fontSize: 11, color: "#484f58" }}>No events yet — start speaking.</div>
        )}
        {entries.map((e, i) => {
          const meta = TYPE_META[e.type] ?? { label: e.type.toUpperCase(), color: "#8b949e" };
          return (
            <div key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start", fontSize: 11, lineHeight: 1.4 }}>
              <span style={{ color: "#484f58", whiteSpace: "nowrap", flexShrink: 0 }}>{e.time}</span>
              <span style={{
                background: meta.color + "22", color: meta.color,
                borderRadius: 3, padding: "0 4px", fontWeight: 700,
                fontSize: 10, flexShrink: 0, lineHeight: "16px",
              }}>{meta.label}</span>
              <span style={{ color: "#8b949e", flexShrink: 0, fontSize: 10 }}>[{e.app}]</span>
              <span style={{
                color: e.success === false ? "#ef4444" : "#e6edf3",
                wordBreak: "break-word",
              }}>{e.text}</span>
              {e.type === "inject" && (
                <span style={{ color: e.success !== false ? "#10b981" : "#ef4444", flexShrink: 0 }}>
                  {e.success !== false ? "✓" : "✗"}
                </span>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function now() {
  return new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function appLabel(bundleId: string): string {
  if (!bundleId || bundleId === "unknown") return "unknown";
  const parts = bundleId.split(".");
  return parts[parts.length - 1] || bundleId;
}

function groupByDay(entries: HistoryEntry[]): Record<string, HistoryEntry[]> {
  const out: Record<string, HistoryEntry[]> = {};
  const today = new Date();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  for (const e of entries) {
    const d = new Date(e.timestamp);
    if (isNaN(d.getTime())) continue;
    const key = sameDay(d, today) ? "Today"
             : sameDay(d, yesterday) ? "Yesterday"
             : d.toLocaleDateString(undefined, { month: "long", day: "numeric" });
    (out[key] ||= []).push(e);
  }
  return out;
}
function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function groupOrder(k: string) { return k === "Today" ? 0 : k === "Yesterday" ? 1 : 2; }
function formatTime(ts: string) {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
