import React, { useEffect, useState } from "react";

interface ApprovalRequest {
  tool: string;
  summary: string;
  params: Record<string, unknown>;
}

export function ApprovalWidget() {
  const [request, setRequest] = useState<ApprovalRequest | null>(null);

  useEffect(() => {
    const off = (window.miniflow as any).onApprovalNeeded?.((e: ApprovalRequest) => {
      setRequest(e);
    });
    return () => off?.();
  }, []);

  if (!request) return null;

  async function respond(approved: boolean) {
    setRequest(null);
    await (window.miniflow as any).sendApproval(approved);
  }

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 0, right: 0,
      background: "var(--bg-secondary, #1c1c1e)",
      borderTop: "1px solid var(--fn-card-border, #3a3a3c)",
      padding: "14px 16px",
      zIndex: 999,
      animation: "slideUp 0.2s ease-out",
    }}>
      <style>{`@keyframes slideUp { from { transform: translateY(100%); opacity: 0; } to { transform: translateY(0); opacity: 1; } }`}</style>

      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                    letterSpacing: "0.08em", color: "var(--accent-brown, #c8882a)",
                    marginBottom: 6 }}>
        Confirm Action
      </div>

      <div style={{ fontSize: 13, color: "var(--text-primary, #e5e5ea)",
                    marginBottom: 12, lineHeight: 1.4 }}>
        {request.summary}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => respond(true)}
          style={{
            flex: 1, padding: "8px 0", borderRadius: 8, border: "none",
            background: "var(--accent-brown, #c8882a)", color: "#fff",
            fontWeight: 600, fontSize: 13, cursor: "pointer",
          }}
        >
          Do it
        </button>
        <button
          onClick={() => respond(false)}
          style={{
            flex: 1, padding: "8px 0", borderRadius: 8,
            border: "1px solid var(--fn-card-border, #3a3a3c)",
            background: "transparent", color: "var(--text-muted, #8e8e93)",
            fontWeight: 600, fontSize: 13, cursor: "pointer",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
