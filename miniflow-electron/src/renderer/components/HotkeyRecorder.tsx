import React, { useEffect, useState } from "react";
import type { HotkeyMode, HotkeyModifier } from "@shared/types";

type Binding = { mode: HotkeyMode; modifier: HotkeyModifier | null; key: string | null };
type TwoHotkeyConfig = { dictation: Binding; command: Binding | null };

function eventToHotkey(e: KeyboardEvent): { modifier: HotkeyModifier | null; key: string | null } {
  const mods: HotkeyModifier[] = [];
  if (e.metaKey) mods.push("cmd");
  if (e.altKey)  mods.push("option");
  if (e.ctrlKey) mods.push("control");
  if (e.shiftKey) mods.push("shift");
  const k = e.code;
  let key: string | null = null;
  if (/^Key[A-Z]$/.test(k)) key = k.slice(3).toLowerCase();
  else if (/^Digit[0-9]$/.test(k)) key = k.slice(5);
  else if (/^F(1[0-2]|[1-9])$/.test(k)) key = k.toLowerCase();
  else if (k === "Space") key = "space";
  else if (k === "Enter") key = "return";
  else if (k === "Tab")   key = "tab";
  else if (k === "Escape") key = "escape";
  else if (k === "Backspace" || k === "Delete") key = "delete";
  else if (k === "ArrowUp")    key = "up";
  else if (k === "ArrowDown")  key = "down";
  else if (k === "ArrowLeft")  key = "left";
  else if (k === "ArrowRight") key = "right";
  return { modifier: mods[0] ?? null, key };
}

function modName(m: HotkeyModifier): string {
  return { fn: "Fn", globe: "🌐", cmd: "⌘", option: "⌥", control: "⌃", shift: "⇧" }[m];
}
function humanLabel(hk: Binding | null): string {
  if (!hk) return "(none)";
  const parts: string[] = [];
  if (hk.modifier) parts.push(modName(hk.modifier));
  if (hk.key) parts.push(hk.key.toUpperCase());
  return parts.join(" + ") || "(none)";
}

export function HotkeySettings() {
  const [cfg, setCfg] = useState<TwoHotkeyConfig | null>(null);
  const [listeningFor, setListeningFor] = useState<"dictation" | "command" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const raw = (await window.miniflow.getHotkey()) as any;
    // Tolerate legacy flat shape coming back from an older backend
    if (raw?.dictation || raw?.command !== undefined) {
      setCfg({
        dictation: raw.dictation ?? { mode: "hold_to_talk", modifier: "fn", key: null },
        command:   raw.command ?? null,
      });
    } else {
      setCfg({
        dictation: { mode: raw?.mode ?? "hold_to_talk", modifier: raw?.modifier ?? "fn", key: raw?.key ?? null },
        command:   null,
      });
    }
  }
  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    if (!listeningFor || !cfg) return;
    function onKey(e: KeyboardEvent) {
      e.preventDefault(); e.stopPropagation();
      if (e.key === "Escape") { setListeningFor(null); return; }
      const { modifier, key } = eventToHotkey(e);
      if (!key) return;
      if (!modifier) {
        setError("Hotkey must include exactly one modifier (Cmd / Option / Ctrl / Shift).");
        return;
      }
      setError(null);
      // Dictation wants hold-to-talk (user speaks while Fn is down).
      // Command wants press-to-toggle (tap once to start, tap again to stop)
      // so the user can return their hand to the keyboard while the LLM thinks.
      const defaultMode: HotkeyMode = listeningFor === "command" ? "press_to_toggle" : "hold_to_talk";
      const current = cfg![listeningFor!] ?? { mode: defaultMode, modifier: null, key: null };
      const next: Binding = { mode: current.mode || defaultMode, modifier, key };
      save({ ...cfg!, [listeningFor!]: next } as TwoHotkeyConfig);
      setListeningFor(null);
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [listeningFor, cfg]);

  async function save(next: TwoHotkeyConfig) {
    try {
      await window.miniflow.setHotkey(next as any);
      await refresh();
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  }
  async function resetToDefaults() {
    await window.miniflow.resetHotkey();
    await refresh();
  }
  async function setDictationFn() {
    if (!cfg) return;
    await save({ ...cfg, dictation: { mode: "hold_to_talk", modifier: "fn", key: null } });
  }
  async function clearCommand() {
    if (!cfg) return;
    await save({ ...cfg, command: null });
  }

  if (!cfg) return <div className="info-msg">Loading…</div>;

  return (
    <div className="stack">
      <div>
        <h3>Dictation hotkey</h3>
        <div className="info-msg" style={{ marginTop: 0, marginBottom: 10 }}>
          Hold to speak. Transcript is grammar-corrected and typed into the focused app.
        </div>
        <div className="row">
          <div className={`hotkey-recorder ${listeningFor === "dictation" ? "listening" : ""}`}
               role="button" aria-pressed={listeningFor === "dictation"}
               onClick={() => setListeningFor("dictation")}>
            {listeningFor === "dictation"
              ? "Press any combination…"
              : <kbd>{humanLabel(cfg.dictation)}</kbd>}
          </div>
          <button className="btn-secondary" onClick={setDictationFn}>Use Fn</button>
        </div>
      </div>

      <div>
        <h3>Command hotkey</h3>
        <div className="info-msg" style={{ marginTop: 0, marginBottom: 10 }}>
          Hold to speak a command. The LLM decides which tool to run — opens apps,
          posts to Slack, sends email, creates calendar events, etc.
        </div>
        <div className="row">
          <div className={`hotkey-recorder ${listeningFor === "command" ? "listening" : ""}`}
               role="button" aria-pressed={listeningFor === "command"}
               onClick={() => setListeningFor("command")}>
            {listeningFor === "command"
              ? "Press any combination…"
              : <kbd>{humanLabel(cfg.command)}</kbd>}
          </div>
          {cfg.command && <button className="btn-secondary" onClick={clearCommand}>Disable</button>}
        </div>
      </div>

      <div className="row">
        <button className="btn-secondary" onClick={resetToDefaults}>Reset all to defaults</button>
      </div>
      {error && <div className="error-msg">{error}</div>}
    </div>
  );
}
