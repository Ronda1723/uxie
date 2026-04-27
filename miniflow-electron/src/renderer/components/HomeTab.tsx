import React, { useEffect, useRef, useState } from "react";
import { ApprovalWidget } from "./ApprovalWidget";
import { UxieMascot, Waveform, Flame } from "./Mascot";
import {
  IconRocket, IconBolt, IconTrophy, IconSearch, IconMic, IconSpark,
  IconCheck, IconX, IconArrow, IconPlay,
} from "./Icons";

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

// Category palette + icon — used to colorize history rows by intent.
// Category is derived from the agent's action tag (search / music / mail / etc.);
// fallbacks to "dictate" when unknown.
type CategoryKey = "search" | "music" | "dictate" | "calendar" | "mail";
const CATEGORY: Record<CategoryKey, { tone: string; label: string; Icon: React.FC<any> }> = {
  search:   { tone: "var(--sky)",    label: "Search",   Icon: IconSearch },
  music:    { tone: "var(--lilac)",  label: "Music",    Icon: IconPlay },
  dictate:  { tone: "var(--peach)",  label: "Dictate",  Icon: IconMic },
  calendar: { tone: "var(--mint)",   label: "Calendar", Icon: IconCheck },
  mail:     { tone: "var(--yellow)", label: "Mail",     Icon: IconArrow },
};

function categorize(e: HistoryEntry): CategoryKey {
  const t = (e.entry_type || "").toLowerCase();
  if (t.includes("search")) return "search";
  if (t.includes("music") || t.includes("spotify")) return "music";
  if (t.includes("calendar") || t.includes("event")) return "calendar";
  if (t.includes("mail") || t.includes("email")) return "mail";
  return "dictate";
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
        setInterim("");
        streaming = "";
        setTimeout(refreshHistory, 1500);
      }
    );
    const offInterim = (window.miniflow as any).onTranscriptionInterim?.(
      (p: { transcript: string }) => {
        if (p?.transcript) setInterim(p.transcript);
      }
    );
    const offErr = (window.miniflow as any).onTranscriptionError?.((msg: string) => setError(msg));
    const offAct = window.miniflow.onAction((a: any) => {
      if (a?.action === "dictation-final" && a?.message) {
        setLastTranscript(a.message);
        streaming = "";
      }
      refreshHistory();
    });
    const offDbg = (window.miniflow as any).onDebugEvent?.((e: any) => {
      if (e?.type === "stt" && e?.text && e.text !== "(empty)") setRawStt(e.text);
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

  const greeting = (() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Welcome back" : "Good evening";
  })();

  return (
    <div className="home">
      {/* ── greeting strip ─────────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "flex-end", justifyContent: "space-between",
        marginBottom: 18,
      }}>
        <div>
          {userName && (
            <div className="hand" style={{
              fontSize: 17, color: "var(--muted)", marginBottom: -4,
              transform: "rotate(-2deg)", display: "inline-block",
            }}>
              hey {userName.split(/\s+/)[0]} —
            </div>
          )}
          <h1 className="serif" style={{
            fontSize: 38, fontWeight: 700, letterSpacing: "-0.03em",
            margin: 0, lineHeight: 1, color: "var(--ink)",
          }}>
            {greeting}
            <span style={{ color: "var(--accent)" }}>.</span>
          </h1>
        </div>
        <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
          {new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
        </div>
      </div>

      {/* ── streak hero (placeholder data until backend wires real values) ── */}
      <StreakHero streak={0} commandsToday={history.length}/>

      {/* ── dictate banner — listening state takes precedence ─────────── */}
      <DictateBanner
        isListening={isListening}
        isProcessing={isProcessing}
        captureMode={captureMode}
        interim={interim}
      />

      {error && <div className="error-msg" style={{ marginBottom: 8 }}>{error}</div>}

      {(lastTranscript || rawStt) && (
        <div style={{
          background: "var(--cream)", border: "1px solid var(--line)",
          borderRadius: 12, padding: "10px 14px",
          display: "flex", flexDirection: "column", gap: 6, marginBottom: 14,
        }}>
          {rawStt && (
            <Labeled label="Heard (raw)">
              <span style={{ fontStyle: "italic", color: "var(--muted)" }}>{rawStt}</span>
            </Labeled>
          )}
          {lastTranscript && (
            <Labeled label="Typed (cleaned)">
              <span style={{ fontSize: 13, lineHeight: 1.4, color: "var(--ink)" }}>{lastTranscript}</span>
            </Labeled>
          )}
        </div>
      )}

      {/* ── command bar — typed commands only; dictation never lands here ── */}
      <CommandBar
        ref={inputRef}
        value={commandText}
        onChange={setCommandText}
        onSubmit={sendCommand}
        placeholder={isListening ? "Listening…" : "Type a command or ask Uxie…"}
        disabled={isListening}
      />

      {/* ── history feed ──────────────────────────────────────────────── */}
      {history.length > 0 && <HistoryTimeline entries={history} onRefresh={refreshHistory}/>}

      <ApprovalWidget />
    </div>
  );
}

/* ── streak hero — big serif number, mascot, weekly check dots ─────── */

function StreakHero({ streak, commandsToday }: { streak: number; commandsToday: number }) {
  const days = ["M", "T", "W", "T", "F", "S", "S"];
  const todayIdx = (new Date().getDay() + 6) % 7; // Mon=0..Sun=6
  // Show as many filled dots as the current streak allows, capped at todayIdx.
  const active = days.map((_, i) => i <= todayIdx && i < streak);

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 14,
      marginBottom: 14,
    }}>
      {/* streak card */}
      <div style={{
        position: "relative", overflow: "hidden",
        padding: "18px 20px", borderRadius: 16,
        background: "linear-gradient(135deg, #f9ecc9 0%, #f2cdb8 100%)",
        border: "1px solid rgba(0,0,0,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{
              fontSize: 10, fontWeight: 600, color: "var(--ink-2)",
              letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4,
            }}>Current streak</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span className="serif" style={{
                fontSize: 56, fontWeight: 700, lineHeight: 1,
                letterSpacing: "-0.04em", color: "var(--ink)",
              }}>{streak}</span>
              <span className="serif" style={{ fontSize: 18, fontStyle: "italic", color: "var(--ink-2)" }}>
                {streak === 1 ? "day" : "days"}
              </span>
              <span style={{ marginLeft: 4, animation: "uxie-bob 2.2s ease-in-out infinite", display: "inline-block" }}>
                <Flame size={22}/>
              </span>
            </div>
            <div style={{
              fontSize: 11.5, color: "var(--ink-2)", marginTop: 4,
              display: "flex", alignItems: "center", gap: 4,
            }}>
              {streak > 0 ? "Keep it going — one dictation a day" : "Press fn for the first one today"}
              <IconSpark size={11} style={{ color: "var(--accent)" }}/>
            </div>
          </div>
          <div style={{ marginTop: -4 }}>
            <UxieMascot size={62} mood="excited"/>
          </div>
        </div>
        {/* week dots */}
        <div style={{ display: "flex", gap: 6, marginTop: 12, alignItems: "center" }}>
          {days.map((d, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
              <div style={{
                width: 22, height: 22, borderRadius: "50%",
                background: active[i] ? "var(--ink)" : i === todayIdx ? "transparent" : "rgba(0,0,0,0.05)",
                border: i === todayIdx ? "1.5px dashed var(--ink)" : "none",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: active[i] ? "var(--paper)" : "var(--ink-2)",
              }}>
                {active[i] && <IconCheck size={11}/>}
              </div>
              <div style={{ fontSize: 9.5, color: "var(--muted)", fontWeight: 600 }}>{d}</div>
            </div>
          ))}
        </div>
      </div>

      {/* stats column */}
      <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: 10 }}>
        <StatTile Icon={IconRocket} tone="var(--sky)" big={String(commandsToday)} label="commands today" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <StatTile Icon={IconBolt}    tone="var(--lilac)" big="—" label="wpm avg" />
          <StatTile Icon={IconTrophy}  tone="var(--mint)"  big="—" label="day record" />
        </div>
      </div>
    </div>
  );
}

function StatTile({ Icon, tone, big, label }: {
  Icon: React.FC<any>; tone: string; big: string; label: string;
}) {
  return (
    <div style={{
      position: "relative", overflow: "hidden",
      padding: "12px 14px", borderRadius: 14,
      background: "var(--paper)", border: "1px solid var(--line)",
      display: "flex", flexDirection: "column", justifyContent: "space-between",
      minHeight: 70,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{
          width: 22, height: 22, borderRadius: 7, background: tone,
          display: "flex", alignItems: "center", justifyContent: "center", color: "var(--ink)",
        }}>
          <Icon size={12}/>
        </div>
        <span style={{
          fontSize: 10, color: "var(--muted)", fontWeight: 600,
          textTransform: "uppercase", letterSpacing: "0.06em",
        }}>{label}</span>
      </div>
      <span className="serif" style={{
        fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em",
        color: "var(--ink)", lineHeight: 1, marginTop: 2,
      }}>{big}</span>
    </div>
  );
}

/* ── dictate banner — main "Hold fn to start" surface, becomes Listening… ── */

function DictateBanner({ isListening, isProcessing, captureMode, interim }: {
  isListening: boolean;
  isProcessing: boolean;
  captureMode: "dictation" | "command";
  interim: string;
}) {
  return (
    <div style={{
      position: "relative", overflow: "hidden",
      padding: "14px 18px", borderRadius: 14,
      background: isListening
        ? "linear-gradient(135deg, #fce8d4 0%, #f7d4b6 100%)"
        : "var(--cream)",
      border: `1px solid ${isListening ? "var(--accent)" : "var(--line)"}`,
      marginBottom: 12,
      transition: "all 0.2s ease",
      display: "flex", alignItems: "center", gap: 14,
    }}>
      <div style={{
        width: 44, height: 44, borderRadius: 12,
        background: isListening ? "var(--accent)" : "var(--tan)",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: isListening ? "white" : "var(--ink-2)",
        transition: "all 0.2s ease",
        transform: isListening ? "scale(1.05)" : "scale(1)",
        boxShadow: isListening ? "0 0 0 8px rgba(217,119,87,0.18)" : "none",
        flexShrink: 0,
      }}>
        <IconMic size={20}/>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>
            {isListening ? "Listening…" : isProcessing ? "Processing…" : "Hold"}
          </span>
          {!isListening && !isProcessing && (
            <>
              <span className="kbd">fn</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>to start dictating</span>
            </>
          )}
          {isListening && (
            <span style={{
              marginLeft: 6, padding: "1px 8px", borderRadius: 999,
              fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase",
              background: captureMode === "command" ? "var(--accent)" : "var(--tan)",
              color: captureMode === "command" ? "white" : "var(--ink-2)",
            }}>
              {captureMode === "command" ? "command" : "dictation"}
            </span>
          )}
        </div>
        <div style={{
          fontSize: 12, color: "var(--muted)", lineHeight: 1.4,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          fontStyle: isListening && interim ? "italic" : "normal",
        }}>
          {isListening
            ? (interim || "Speak naturally — Uxie is transcribing right now.")
            : isProcessing
              ? "Cleaning up + sending to the agent…"
              : "Speak naturally — Uxie transcribes and executes commands in any app."}
        </div>
      </div>
      <div style={{ minWidth: 90, display: "flex", justifyContent: "flex-end", flexShrink: 0 }}>
        <Waveform
          bars={14}
          color={isListening ? "var(--accent)" : "var(--muted-2)"}
          active={isListening}
          height={24}
        />
      </div>
    </div>
  );
}

/* ── command bar ─────────────────────────────────────────────────── */

const CommandBar = React.forwardRef<HTMLInputElement, {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  disabled?: boolean;
}>(function CommandBar({ value, onChange, onSubmit, placeholder, disabled }, ref) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "9px 14px", borderRadius: 11,
      background: "var(--paper)", border: "1px solid var(--line)",
      marginBottom: 18,
      opacity: disabled ? 0.6 : 1,
    }}>
      <IconSearch size={14} style={{ color: "var(--muted)" }}/>
      <input
        ref={ref}
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") onSubmit(); }}
        disabled={disabled}
        style={{
          flex: 1, border: "none", outline: "none", background: "transparent",
          fontSize: 13, color: "var(--ink)",
          fontFamily: "inherit",
        }}
      />
      <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>↵</span>
    </div>
  );
});

/* ── history timeline ───────────────────────────────────────────── */

function HistoryTimeline({ entries, onRefresh }: { entries: HistoryEntry[]; onRefresh: () => void }) {
  const groups = groupByDay(entries);
  const keys = Object.keys(groups).sort((a, b) => groupOrder(a) - groupOrder(b));

  async function clearAll() {
    if (!confirm("Clear all history?")) return;
    await window.miniflow.clearHistory();
    onRefresh();
  }

  return (
    <div>
      {keys.map((k) => (
        <div key={k} style={{ marginBottom: 14 }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 8,
          }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="serif" style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>{k}</span>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>· {groups[k].length}</span>
            </div>
            {k === "Today" && (
              <button
                onClick={clearAll}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  fontSize: 11, color: "var(--muted)",
                  textDecoration: "underline", textUnderlineOffset: 3,
                  fontFamily: "inherit",
                }}
              >Clear all</button>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {groups[k].slice(0, 20).map((e, i) => <HistoryRow key={i} entry={e}/>)}
          </div>
        </div>
      ))}
    </div>
  );
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const cat = CATEGORY[categorize(entry)];
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "grid",
        gridTemplateColumns: "56px 22px 1fr auto",
        gap: 10, alignItems: "center",
        padding: "8px 10px", borderRadius: 9,
        background: hover ? "var(--cream)" : "transparent",
        transition: "background 0.12s ease",
      }}
    >
      <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>
        {formatTime(entry.timestamp)}
      </span>
      <div style={{
        width: 20, height: 20, borderRadius: 6, background: cat.tone,
        display: "flex", alignItems: "center", justifyContent: "center", color: "var(--ink)",
      }}>
        <cat.Icon size={11}/>
      </div>
      <div style={{
        fontSize: 12.5, color: "var(--ink-2)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {entry.transcript}
      </div>
      <span style={{
        color: entry.success ? "var(--green)" : "var(--red)",
        display: "flex", alignItems: "center",
      }}>
        {entry.success ? <IconCheck size={13}/> : <IconX size={13}/>}
      </span>
    </div>
  );
}

/* ── tiny helper ─────────────────────────────────────────────────── */

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontSize: 9.5, fontWeight: 600, color: "var(--muted)",
        textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2,
      }}>{label}</div>
      <div style={{ fontSize: 12, lineHeight: 1.4 }}>{children}</div>
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
  return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
}
function groupOrder(k: string) { return k === "Today" ? 0 : k === "Yesterday" ? 1 : 2; }
function formatTime(ts: string) {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
