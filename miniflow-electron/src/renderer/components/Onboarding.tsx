import React, { useEffect, useState } from "react";

interface PermissionState {
  id: "microphone" | "accessibility" | "inputMonitoring";
  status: "granted" | "denied" | "not-determined" | "unknown";
  canAutoRequest: boolean;
  hint: string;
}

const LABELS: Record<PermissionState["id"], string> = {
  microphone: "Microphone",
  accessibility: "Accessibility",
  inputMonitoring: "Input Monitoring",
};

const ICONS: Record<PermissionState["id"], string> = {
  microphone: "🎙",
  accessibility: "⌨︎",
  inputMonitoring: "⌥",
};

type OnboardStep = "auth" | "permissions";

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<OnboardStep>("auth");

  if (step === "auth") {
    return <AuthStep onDone={() => setStep("permissions")} />;
  }
  return <PermissionsStep onDone={onDone} />;
}

// ── Auth step ─────────────────────────────────────────────────────────────────

function AuthStep({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [phase, setPhase] = useState<"email" | "otp">("email");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function sendOtp() {
    setErr(null);
    setBusy(true);
    try {
      await (window.miniflow as any).sendOtp(email.trim(), referralCode.trim() || undefined);
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
    <div className="overlay">
      <div className="modal onboarding" role="dialog" aria-modal="true">
        <div className="onboarding-head">
          <div className="onboarding-title">Welcome to Uxie</div>
          <div className="onboarding-sub">
            Sign in with your email — no password needed.
          </div>
        </div>

        <div className="stack" style={{ padding: "0 24px" }}>
          {phase === "email" ? (
            <>
              <div className="field">
                <label htmlFor="ob-email">Email address</label>
                <input
                  id="ob-email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  autoFocus
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && email.trim()) sendOtp(); }}
                />
              </div>
              <div className="field">
                <label htmlFor="ob-ref">Referral code (optional)</label>
                <input
                  id="ob-ref"
                  type="text"
                  placeholder="XXXXXXXX"
                  value={referralCode}
                  onChange={(e) => setReferralCode(e.target.value.toUpperCase())}
                />
              </div>
            </>
          ) : (
            <div className="field">
              <label htmlFor="ob-otp">6-digit code sent to {email}</label>
              <input
                id="ob-otp"
                type="text"
                placeholder="123456"
                value={code}
                maxLength={6}
                autoFocus
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                onKeyDown={(e) => { if (e.key === "Enter" && code.length === 6) verifyOtp(); }}
              />
              <div className="hint">
                Check your inbox. The code expires in 10 minutes.{" "}
                <button
                  className="btn-link"
                  onClick={() => { setPhase("email"); setCode(""); setErr(null); }}
                  style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", padding: 0, fontSize: "inherit" }}
                >
                  Change email
                </button>
              </div>
            </div>
          )}

          {err && <div className="error-msg">{err}</div>}
        </div>

        <div className="onboarding-foot">
          {phase === "email" ? (
            <button
              className="btn-primary"
              onClick={sendOtp}
              disabled={!email.trim() || busy}
            >
              {busy ? "Sending…" : "Send code"}
            </button>
          ) : (
            <button
              className="btn-primary"
              onClick={verifyOtp}
              disabled={code.length !== 6 || busy}
            >
              {busy ? "Verifying…" : "Sign in"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Permissions step ──────────────────────────────────────────────────────────

function PermissionsStep({ onDone }: { onDone: () => void }) {
  const [perms, setPerms] = useState<PermissionState[] | null>(null);
  const [busy, setBusy] = useState<PermissionState["id"] | null>(null);

  async function refresh() {
    const next = await (window.miniflow as any).getPermissions() as PermissionState[];
    setPerms(next);
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    (window.miniflow as any).pinWindow?.(true);
    return () => {
      clearInterval(t);
      (window.miniflow as any).pinWindow?.(false);
    };
  }, []);

  async function request(id: PermissionState["id"]) {
    setBusy(id);
    try { await (window.miniflow as any).requestPermission(id); }
    finally { setBusy(null); await refresh(); }
  }

  if (!perms) return null;

  const allGranted = perms.every((p) => p.status === "granted");

  return (
    <div className="overlay">
      <div className="modal onboarding" role="dialog" aria-modal="true">
        <div className="onboarding-head">
          <div className="onboarding-title">Grant permissions</div>
          <div className="onboarding-sub">
            Uxie needs three macOS permissions to work. Grant them here — no need
            to dig through System Settings.
          </div>
        </div>

        <div className="onboarding-list">
          {perms.map((p) => (
            <PermRow key={p.id} perm={p} busy={busy === p.id}
                     onGrant={() => request(p.id)} />
          ))}
        </div>

        <div className="onboarding-foot">
          <button
            className="btn-primary"
            onClick={onDone}
            disabled={!allGranted}
            title={allGranted ? "" : "Grant all three permissions to continue"}
          >
            {allGranted ? "Continue" : "Waiting on permissions…"}
          </button>
          <button className="btn-secondary" onClick={onDone}>Skip for now</button>
        </div>
      </div>
    </div>
  );
}

function PermRow({ perm, busy, onGrant }: {
  perm: PermissionState; busy: boolean; onGrant: () => void;
}) {
  const granted = perm.status === "granted";
  return (
    <div className={`perm-row ${granted ? "granted" : ""}`}>
      <div className="perm-icon">{ICONS[perm.id]}</div>
      <div className="perm-body">
        <div className="perm-title">
          {LABELS[perm.id]}
          {granted && <span className="chip-tag ready" style={{ marginLeft: 8 }}>granted</span>}
        </div>
        <div className="perm-hint">{perm.hint}</div>
      </div>
      {!granted && (
        <button className="btn-primary" onClick={onGrant} disabled={busy}>
          {busy ? "…" : perm.canAutoRequest ? "Grant" : "Open Settings"}
        </button>
      )}
      {granted && <span className="perm-check">✓</span>}
    </div>
  );
}
