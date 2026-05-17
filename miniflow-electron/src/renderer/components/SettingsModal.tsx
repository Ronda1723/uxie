import React, { useEffect, useState } from "react";
import { HotkeySettings } from "./HotkeyRecorder";

type SettingsTab = "account" | "hotkey" | "connectors" | "updates";

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<SettingsTab>("account");

  return (
    <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-header">
          <span className="modal-title">Settings</span>
          <button className={`modal-tab ${tab === "account"    ? "active" : ""}`} onClick={() => setTab("account")}>Account</button>
          <button className={`modal-tab ${tab === "connectors" ? "active" : ""}`} onClick={() => setTab("connectors")}>Connectors</button>
          <button className={`modal-tab ${tab === "hotkey"     ? "active" : ""}`} onClick={() => setTab("hotkey")}>Hotkey</button>
          <button className={`modal-tab ${tab === "updates"    ? "active" : ""}`} onClick={() => setTab("updates")}>Updates</button>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          {tab === "account"    && <AccountTab />}
          {tab === "connectors" && <ConnectorsTab />}
          {tab === "hotkey"     && <HotkeySettings />}
          {tab === "updates"    && <UpdatesTab />}
        </div>
      </div>
    </div>
  );
}

// ── Updates tab ───────────────────────────────────────────────────────────────

type UpdatePhase = "idle" | "checking" | "available" | "not-available" | "downloading" | "downloaded" | "error";

function UpdatesTab() {
  const mf = window.miniflow as any;
  const [currentVersion, setCurrentVersion] = useState<string>("");
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [availableVersion, setAvailableVersion] = useState<string>("");
  const [progressPct, setProgressPct] = useState<number>(0);
  const [errMsg, setErrMsg] = useState<string>("");

  useEffect(() => {
    mf.getAppVersion?.().then((v: string) => setCurrentVersion(v || ""));

    const unsub = mf.onUpdaterEvent?.((e: { kind: string; payload: any }) => {
      switch (e.kind) {
        case "checking-for-update":
          setPhase("checking"); setErrMsg("");
          break;
        case "update-available":
          setPhase("available");
          setAvailableVersion(e.payload?.version ?? "");
          break;
        case "update-not-available":
          setPhase("not-available");
          break;
        case "download-progress":
          setPhase("downloading");
          setProgressPct(Math.round(e.payload?.percent ?? 0));
          break;
        case "update-downloaded":
          setPhase("downloaded");
          setAvailableVersion(e.payload?.version ?? availableVersion);
          break;
        case "error":
          setPhase("error");
          setErrMsg(String(e.payload?.message ?? e.payload ?? "Unknown error"));
          break;
      }
    });
    return () => { try { unsub?.(); } catch {} };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function check() {
    setPhase("checking"); setErrMsg("");
    const r = await mf.checkForUpdate?.();
    if (!r?.ok) {
      setPhase("error");
      setErrMsg(r?.reason ?? "Couldn't reach the update server. Are you online?");
    }
    // success path is handled via onUpdaterEvent (update-available / update-not-available)
  }

  async function download() {
    const r = await mf.downloadUpdate?.();
    if (!r?.ok) {
      setPhase("error");
      setErrMsg(r?.reason ?? "Download failed.");
    }
  }

  function installNow() {
    mf.installUpdateNow?.();
  }

  return (
    <div className="stack">
      <div className="field">
        <label>Current version</label>
        <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>
          {currentVersion ? `v${currentVersion}` : "—"}
        </div>
      </div>

      {phase === "idle" || phase === "checking" || phase === "not-available" || phase === "error" ? (
        <div className="row">
          <button className="btn-primary" onClick={check} disabled={phase === "checking"}>
            {phase === "checking" ? "Checking…" : "Check for updates"}
          </button>
          {phase === "not-available" && (
            <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 10 }}>
              You're on the latest version.
            </span>
          )}
        </div>
      ) : null}

      {phase === "available" && (
        <div className="field">
          <label>Update available</label>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            <strong>v{availableVersion}</strong> is available.
          </div>
          <div className="row">
            <button className="btn-primary" onClick={download}>Download update</button>
          </div>
        </div>
      )}

      {phase === "downloading" && (
        <div className="field">
          <label>Downloading v{availableVersion}…</label>
          <div style={{
            height: 6, background: "var(--surface-2)", borderRadius: 3, overflow: "hidden", margin: "6px 0",
          }}>
            <div style={{
              width: `${progressPct}%`, height: "100%", background: "var(--accent)",
              transition: "width 200ms ease-out",
            }} />
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{progressPct}%</div>
        </div>
      )}

      {phase === "downloaded" && (
        <div className="field">
          <label>Ready to install</label>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            <strong>v{availableVersion}</strong> downloaded. Restart Uxie to install.
          </div>
          <div className="row">
            <button className="btn-primary" onClick={installNow}>Restart &amp; install</button>
          </div>
        </div>
      )}

      {errMsg && (
        <div className="error-msg" style={{ marginTop: 8 }}>{errMsg}</div>
      )}

      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
        Uxie auto-checks for updates at launch. You can install whenever you want — your work isn't interrupted.
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

// ── Connectors tab ────────────────────────────────────────────────────────────

const OAUTH_PROVIDERS = [
  { id: "google", icon: "🔵", label: "Google", hint: "Gmail + Google Calendar via your Google account" },
  { id: "slack",  icon: "💬", label: "Slack",  hint: "Post messages, read channels, summarize threads" },
];

const MCP_META: Record<string, { icon: string; label: string; hint: string; keyLabel: string }> = {
  github: { icon: "🐙", label: "GitHub",  hint: "Create issues, PRs, search repos",   keyLabel: "Personal Access Token" },
  linear: { icon: "🔷", label: "Linear",  hint: "Create and update issues via voice",  keyLabel: "API Key" },
  notion: { icon: "📝", label: "Notion",  hint: "Search and create pages",             keyLabel: "Integration Token" },
};

interface MCPServerStatus {
  id: string; display: string; always_on: boolean;
  env_keys: string[]; configured: boolean; running: boolean;
}

function ConnectorsTab() {
  const [connected, setConnected] = useState<string[]>([]);
  const [servers, setServers] = useState<MCPServerStatus[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const mf = window.miniflow as any;

  async function loadStatus() {
    try {
      const [providers, mcpList] = await Promise.all([
        mf.getConnectedProviders?.() as string[],
        mf.getMCPStatus?.() as MCPServerStatus[],
      ]);
      if (providers) setConnected(providers);
      if (mcpList) setServers(mcpList.filter((s: MCPServerStatus) => !s.always_on));
    } catch {}
  }

  useEffect(() => {
    loadStatus();
    const unsub = mf.onOAuthConnected?.((provider: string) => {
      setConnected((prev) => prev.includes(provider) ? prev : [...prev, provider]);
    });
    return () => { try { unsub?.(); } catch {} };
  }, []);

  async function oauthConnect(provider: string) {
    setBusy(provider);
    try {
      await mf.startOAuth?.(provider);
      // Connection is confirmed by the onOAuthConnected event
    } catch (e: any) {
      alert(`Failed to start OAuth: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  }

  async function oauthDisconnect(provider: string) {
    setBusy(provider);
    try {
      await mf.disconnectProvider?.(provider);
      setConnected((prev) => prev.filter((p) => p !== provider));
    } catch (e: any) {
      alert(`Failed to disconnect: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  }

  async function mcpConnect(serverId: string, envKey: string) {
    const value = inputs[serverId]?.trim();
    if (!value) return;
    setBusy(serverId);
    try {
      const result = await mf.connectMCPServer?.(serverId, { [envKey]: value });
      if (result?.status) setServers((result.status as MCPServerStatus[]).filter((s: MCPServerStatus) => !s.always_on));
      setSaved(serverId);
      setTimeout(() => setSaved(null), 2500);
    } catch (e: any) {
      alert(`Failed: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  }

  async function mcpDisconnect(serverId: string) {
    setBusy(serverId);
    try {
      await mf.disconnectMCPServer?.(serverId);
      await loadStatus();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="settings-section">
      {/* ── OAuth accounts (Google, Slack) ── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
          Connected accounts
        </div>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
          Sign in with your account — Uxie uses Gmail, Calendar, and Slack tools directly.
        </p>
        {OAUTH_PROVIDERS.map(({ id, icon, label, hint }) => {
          const isConnected = connected.includes(id);
          const isBusy = busy === id;
          return (
            <div key={id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0", borderBottom: "1px solid var(--fn-card-border)" }}>
              <span style={{ fontSize: 18, width: 24, textAlign: "center" }}>{icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{hint}</div>
                {isConnected && <div style={{ fontSize: 11, color: "#10b981", marginTop: 2 }}>Connected ✓</div>}
              </div>
              {isConnected ? (
                <button className="btn-secondary" onClick={() => oauthDisconnect(id)} disabled={isBusy}
                  style={{ fontSize: 12, padding: "4px 10px" }}>
                  {isBusy ? "…" : "Disconnect"}
                </button>
              ) : (
                <button className="btn-primary" onClick={() => oauthConnect(id)} disabled={isBusy}
                  style={{ fontSize: 12, padding: "4px 12px" }}>
                  {isBusy ? "…" : "Connect"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* ── API connectors (GitHub, Linear, Notion via MCP) ── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
          API connectors
        </div>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
          Paste one token to connect. Stored locally on your Mac, never sent to our servers.
        </p>
        {servers.filter((s) => MCP_META[s.id]).map((srv) => {
          const meta = MCP_META[srv.id];
          const envKey = srv.env_keys[0];
          const isBusy = busy === srv.id;
          const wasSaved = saved === srv.id;
          return (
            <div key={srv.id} style={{ padding: "12px 0", borderBottom: "1px solid var(--fn-card-border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: srv.running ? 0 : 8 }}>
                <span style={{ fontSize: 18, width: 24, textAlign: "center" }}>{meta.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{meta.label}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{meta.hint}</div>
                  {srv.running && <div style={{ fontSize: 11, color: "#10b981", marginTop: 2 }}>Connected ✓</div>}
                </div>
                {srv.running && (
                  <button className="btn-secondary" onClick={() => mcpDisconnect(srv.id)} disabled={isBusy}
                    style={{ fontSize: 12, padding: "4px 10px" }}>
                    {isBusy ? "…" : "Disconnect"}
                  </button>
                )}
              </div>
              {!srv.running && (
                <div style={{ display: "flex", gap: 8, paddingLeft: 34 }}>
                  <input
                    type="password"
                    placeholder={meta.keyLabel}
                    value={inputs[srv.id] ?? ""}
                    onChange={(e) => setInputs((p) => ({ ...p, [srv.id]: e.target.value }))}
                    style={{ flex: 1, fontSize: 12 }}
                    onKeyDown={(e) => { if (e.key === "Enter") mcpConnect(srv.id, envKey); }}
                  />
                  <button className="btn-primary" onClick={() => mcpConnect(srv.id, envKey)}
                    disabled={isBusy || !inputs[srv.id]?.trim()}
                    style={{ fontSize: 12, padding: "4px 12px", whiteSpace: "nowrap" }}>
                    {isBusy ? "…" : wasSaved ? "✓ Connected" : "Connect"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Browser automation ── */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Browser automation
          </span>
          <span style={{ fontSize: 11, background: "#10b98120", color: "#10b981", borderRadius: 4, padding: "1px 6px", fontWeight: 500 }}>
            Always on
          </span>
        </div>
        <p style={{ fontSize: 11, color: "var(--text-muted)" }}>
          Uxie can control any website — book restaurants, fill forms, read pages — using a built-in browser. No setup needed.
        </p>
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

