import React, { useState } from "react";
import { ProviderPicker } from "./ProviderPicker";
import { HotkeySettings } from "./HotkeyRecorder";

type SettingsTab = "keys" | "stt" | "hotkey" | "profile" | "advanced";

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<SettingsTab>("keys");

  return (
    <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-header">
          <span className="modal-title">Settings</span>
          <button className={`modal-tab ${tab === "keys" ? "active" : ""}`} onClick={() => setTab("keys")}>LLM</button>
          <button className={`modal-tab ${tab === "stt" ? "active" : ""}`} onClick={() => setTab("stt")}>Speech</button>
          <button className={`modal-tab ${tab === "hotkey" ? "active" : ""}`} onClick={() => setTab("hotkey")}>Hotkey</button>
          <button className={`modal-tab ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>Profile</button>
          <button className={`modal-tab ${tab === "advanced" ? "active" : ""}`} onClick={() => setTab("advanced")}>Advanced</button>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          {tab === "keys"     && <ProviderPicker />}
          {tab === "stt"      && <SpeechTab />}
          {tab === "hotkey"   && <HotkeySettings />}
          {tab === "profile"  && <ProfileTab />}
          {tab === "advanced" && <AdvancedTab />}
        </div>
      </div>
    </div>
  );
}

function SpeechTab() {
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      await (window.miniflow as any).saveSmallestKey(key.trim());
      setSaved(true); setKey("");
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }
  return (
    <div className="stack">
      <div className="field">
        <label htmlFor="smallest">Smallest AI API key (speech-to-text)</label>
        <input id="smallest" type="password" placeholder="waves_..." value={key}
               onChange={(e) => setKey(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        <div className="hint">
          Get one at <code>waves.smallest.ai</code> → Dashboard. Used only for transcription
          while you hold your hotkey; never leaves your Mac except to Smallest AI's API.
        </div>
      </div>
      <div className="row">
        <button className="btn-primary" onClick={save} disabled={!key.trim()}>
          {saved ? "✓ Saved" : "Save"}
        </button>
        {saved && <span style={{ color: "var(--success-green)", fontSize: 11 }}>Key stored.</span>}
      </div>
      {err && <div className="error-msg">{err}</div>}
    </div>
  );
}

function ProfileTab() {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(false);
  async function save() {
    try {
      await fetch("http://127.0.0.1:8765/invoke/save_user_name", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setSaved(true); setTimeout(() => setSaved(false), 1500);
    } catch {}
  }
  return (
    <div className="stack">
      <div className="field">
        <label htmlFor="pname">Your name</label>
        <input id="pname" type="text" value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Rounak" />
        <div className="hint">Personalizes the welcome header and the sign-off in drafted emails.</div>
      </div>
      <div className="row">
        <button className="btn-primary" onClick={save} disabled={!name.trim()}>Save</button>
        {saved && <span style={{ color: "var(--success-green)", fontSize: 11 }}>✓ Saved</span>}
      </div>
    </div>
  );
}

function AdvancedTab() {
  async function revealKeys() {
    try { await (window.miniflow as any).revealKeysFile(); } catch {}
  }
  async function revealLog()          { try { await (window.miniflow as any).revealLog();       } catch {} }
  async function revealMiniflowDir()  { try { await (window.miniflow as any).openMiniflowDir(); } catch {} }
  return (
    <div className="stack">
      <div>
        <h4>Where are my LLM keys stored?</h4>
        <div className="info-msg">
          In a plain JSON file at <code>~/miniflow/llm_keys.json</code> (chmod 600).
          Edit it by hand or use the button below to reveal it in Finder.
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn-secondary" onClick={revealKeys}>Reveal keys file</button>
          <button className="btn-secondary" onClick={revealMiniflowDir}>Open ~/miniflow/</button>
        </div>
      </div>

      <div>
        <h4>Logs</h4>
        <div className="info-msg">
          Everything the Python backend does (Waves transcripts, LLM calls, errors)
          is appended to <code>~/miniflow/miniflow.log</code>. Tail it from a terminal
          with <code>tail -f ~/miniflow/miniflow.log</code>.
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn-secondary" onClick={revealLog}>Reveal log in Finder</button>
        </div>
      </div>
      <div>
        <h4>Data locations</h4>
        <div className="info-msg">
          Config: <code>~/miniflow/miniflow_settings.json</code><br />
          Hotkey: <code>~/miniflow/hotkey.json</code><br />
          Logs: <code>~/miniflow/miniflow.log</code><br />
          History: <code>~/miniflow/history.json</code>
        </div>
      </div>
      <div>
        <h4>Developer</h4>
        <div className="info-msg">Cmd + Option + I toggles DevTools on the popover.</div>
      </div>
      <div>
        <h4>Permissions</h4>
        <div className="info-msg">
          Re-run the onboarding to review or re-request Microphone / Accessibility /
          Input Monitoring grants.
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn-secondary" onClick={() => {
            localStorage.removeItem("miniflow.onboarded");
            location.reload();
          }}>
            Re-run onboarding
          </button>
        </div>
      </div>
      <div className="row" style={{ marginTop: 20 }}>
        <button className="btn-danger" onClick={() => window.miniflow.quit()}>Quit MiniFlow</button>
      </div>
    </div>
  );
}
