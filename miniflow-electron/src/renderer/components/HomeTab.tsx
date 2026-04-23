import React, { useEffect, useRef, useState } from "react";
import { ApprovalWidget } from "./ApprovalWidget";

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


export function HomeTab({ userName, isListening, isProcessing, captureMode = "dictation" }: Props) {
  const [commandText, setCommandText] = useState("");
  const [lastTranscript, setLastTranscript] = useState<string>("");
  const [interim, setInterim] = useState<string>("");
  const [rawStt, setRawStt] = useState<string>("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function refreshHistory() {
    try {
      const raw = (await window.miniflow.getHistory()) as HistoryEntry[];
      setHistory(Array.isArray(raw) ? raw : []);
    } catch { /* backend may not be ready */ }
  }

  useEffect(() => { refreshHistory(); }, []);

  // Reset the live interim preview whenever we stop listening, so stale
  // partials don't linger until the next session starts.
  useEffect(() => {
    if (!isListening) setInterim("");
  }, [isListening]);

  useEffect(() => {
    let streaming = "";
    const offChunk = (window.miniflow as any).onDictationChunk?.((chunk: string) => {
      streaming += chunk;
      setLastTranscript(streaming);
    });
    const offTx = (window.miniflow as any).onTranscription?.(
      (p: { transcript: string; is_final: boolean; is_session?: boolean }) => {
        if (!p?.transcript || !p.is_session) return;
        setLastTranscript(p.transcript);
        setInterim("");        // final transcript arrived; clear partial
        streaming = "";
        setTimeout(refreshHistory, 1500);
      }
    );
    const offInterim = (window.miniflow as any).onTranscriptionInterim?.(
      (p: { transcript: string }) => {
        if (p?.transcript) setInterim(p.transcript);
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
      refreshHistory();
    });
    // Debug events carry raw STT and LLM output for comparison
    const offDbg = (window.miniflow as any).onDebugEvent?.((e: any) => {
      if (e?.type === "stt" && e?.text && e.text !== "(empty)") {
        setRawStt(e.text);
      }
    });
    return () => { offChunk?.(); offTx?.(); offInterim?.(); offErr?.(); offAct?.(); offDbg?.(); };
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
                {interim && (
                  <div className="desc" style={{
                    marginTop: 6, fontStyle: "italic", opacity: 0.75,
                    fontSize: 13, lineHeight: 1.4,
                  }}>
                    {interim}
                  </div>
                )}
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
      {(lastTranscript || rawStt) && (
        <div className="section" style={{
          background: "var(--fn-card-bg)", border: "1px solid var(--fn-card-border)",
          borderRadius: 10, padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6,
        }}>
          {rawStt && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
                            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>
                Heard (raw)
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.4, color: "var(--text-muted)", fontStyle: "italic" }}>
                {rawStt}
              </div>
            </div>
          )}
          {lastTranscript && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)",
                            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>
                Typed (cleaned)
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.4 }}>{lastTranscript}</div>
            </div>
          )}
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

      {/* History */}
      {history.length > 0 && <HistoryGrouped entries={history} onRefresh={refreshHistory} />}

      {/* Approval widget — slides up from bottom when agent needs confirmation */}
      <ApprovalWidget />
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
