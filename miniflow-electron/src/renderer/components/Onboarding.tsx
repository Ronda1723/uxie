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

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [perms, setPerms] = useState<PermissionState[] | null>(null);
  const [busy, setBusy] = useState<PermissionState["id"] | null>(null);

  async function refresh() {
    const next = await (window.miniflow as any).getPermissions() as PermissionState[];
    setPerms(next);
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);  // poll so Input Monitoring toggles show up live
    // Pin the popover so it doesn't auto-hide when the macOS permission prompt steals focus.
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
  const required = perms;  // all three are required

  return (
    <div className="overlay">
      <div className="modal onboarding" role="dialog" aria-modal="true">
        <div className="onboarding-head">
          <div className="onboarding-title">Welcome to MiniFlow</div>
          <div className="onboarding-sub">
            MiniFlow needs three macOS permissions to work. Grant them here — no need
            to dig through System Settings.
          </div>
        </div>

        <div className="onboarding-list">
          {required.map((p) => (
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
