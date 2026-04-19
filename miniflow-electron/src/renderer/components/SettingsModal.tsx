import React, { useEffect, useState } from "react";
import { HotkeySettings } from "./HotkeyRecorder";

type SettingsTab = "account" | "speech" | "hotkey";

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<SettingsTab>("account");

  return (
    <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-header">
          <span className="modal-title">Settings</span>
          <button className={`modal-tab ${tab === "account" ? "active" : ""}`} onClick={() => setTab("account")}>Account</button>
          <button className={`modal-tab ${tab === "speech"  ? "active" : ""}`} onClick={() => setTab("speech")}>Speech</button>
          <button className={`modal-tab ${tab === "hotkey"  ? "active" : ""}`} onClick={() => setTab("hotkey")}>Hotkey</button>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          {tab === "account" && <AccountTab />}
          {tab === "speech"  && <SpeechTab />}
          {tab === "hotkey"  && <HotkeySettings />}
        </div>
      </div>
    </div>
  );
}

// ── Account tab ───────────────────────────────────────────────────────────────

interface UserStatus {
  email?: string;
  tier?: string;
  free_days_remaining?: number;
  dictation_count?: number;
  command_count?: number;
  referral_code?: string;
  referral_link?: string;
}

function AccountTab() {
  const [user, setUser] = useState<UserStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [showLogin, setShowLogin] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const local = await (window.miniflow as any).getUxieUser();
      if (local?.access_token) {
        setUser(local);
        // Refresh from server in background
        (window.miniflow as any).getUserStatus().then((fresh: any) => {
          if (fresh && !fresh.error) setUser(fresh);
        }).catch(() => {});
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function logout() {
    setLoggingOut(true);
    try {
      await (window.miniflow as any).logout();
      setUser(null);
    } finally {
      setLoggingOut(false);
    }
  }

  function copyLink() {
    if (!user?.referral_link) return;
    navigator.clipboard.writeText(user.referral_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return <div className="stack" style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>;
  }

  if (!user?.email) {
    return <LoginPanel onDone={load} />;
  }

  const tierLabel = user.tier === "pro" ? "Pro" : "Free";
  const daysLeft = user.free_days_remaining ?? 0;

  return (
    <div className="stack">
      <div className="field">
        <label>Signed in as</label>
        <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>{user.email}</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
          Plan: <strong>{tierLabel}</strong>
          {user.tier !== "pro" && daysLeft > 0 && ` — ${daysLeft} free days remaining`}
        </div>
      </div>

      {user.tier !== "pro" && (
        <div className="field">
          <label>Usage this month</label>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Dictation corrections: {user.dictation_count ?? 0} / 100
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Commands: {user.command_count ?? 0} / 50
          </div>
        </div>
      )}

      {user.referral_code && (
        <div className="field">
          <label>Refer a friend — both get +30 free days</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <code style={{ fontSize: 12, background: "var(--surface-2)", padding: "3px 8px", borderRadius: 4, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {user.referral_link ?? `https://uxie.ai/r/${user.referral_code}`}
            </code>
            <button className="btn-secondary" onClick={copyLink} style={{ whiteSpace: "nowrap" }}>
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      <div className="row">
        <button className="btn-secondary" onClick={logout} disabled={loggingOut}>
          {loggingOut ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </div>
  );
}

function LoginPanel({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [phase, setPhase] = useState<"email" | "otp">("email");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function sendOtp() {
    setErr(null);
    setBusy(true);
    try {
      await (window.miniflow as any).sendOtp(email.trim());
      setPhase("otp");
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp() {
    setErr(null);
    setBusy(true);
    try {
      await (window.miniflow as any).verifyOtp(email.trim(), code.trim());
      onDone();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
        Sign in to use Uxie's cloud LLM — no API keys needed.
      </div>

      {phase === "email" ? (
        <div className="field">
          <label htmlFor="s-email">Email address</label>
          <input
            id="s-email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && email.trim()) sendOtp(); }}
          />
        </div>
      ) : (
        <div className="field">
          <label htmlFor="s-otp">6-digit code sent to {email}</label>
          <input
            id="s-otp"
            type="text"
            placeholder="123456"
            value={code}
            maxLength={6}
            autoFocus
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            onKeyDown={(e) => { if (e.key === "Enter" && code.length === 6) verifyOtp(); }}
          />
          <div className="hint">
            <button
              style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", padding: 0, fontSize: "inherit" }}
              onClick={() => { setPhase("email"); setCode(""); setErr(null); }}
            >
              Change email
            </button>
          </div>
        </div>
      )}

      {err && <div className="error-msg">{err}</div>}

      <div className="row">
        {phase === "email" ? (
          <button className="btn-primary" onClick={sendOtp} disabled={!email.trim() || busy}>
            {busy ? "Sending…" : "Send code"}
          </button>
        ) : (
          <button className="btn-primary" onClick={verifyOtp} disabled={code.length !== 6 || busy}>
            {busy ? "Verifying…" : "Sign in"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Speech tab ────────────────────────────────────────────────────────────────

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
      <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
        When signed in to Uxie, speech-to-text is handled automatically.
        Enter your own Smallest AI key here to use it instead.
      </div>
      <div className="field">
        <label htmlFor="smallest">Smallest AI (Waves) API key</label>
        <input id="smallest" type="password" placeholder="waves_..." value={key}
               onChange={(e) => setKey(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        <div className="hint">
          Get one at <code>waves.smallest.ai</code> → Dashboard.
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
