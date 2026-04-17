import React, { useEffect, useState } from "react";

export function SnippetsTab() {
  const [snips, setSnips] = useState<Record<string, string>>({});
  const [trigger, setTrigger] = useState("");
  const [expansion, setExpansion] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const s = (await (window.miniflow as any).getSnippets()) as Record<string, string>;
      setSnips(s || {});
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  useEffect(() => { refresh(); }, []);

  async function add() {
    if (!trigger.trim() || !expansion.trim()) return;
    try {
      await (window.miniflow as any).addSnippet(trigger.trim(), expansion);
      setTrigger(""); setExpansion(""); setErr(null);
      await refresh();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }
  async function remove(t: string) {
    await (window.miniflow as any).removeSnippet(t);
    await refresh();
  }

  const entries = Object.entries(snips).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="home">
      <h1>Snippets</h1>
      <div className="info-msg" style={{ marginBottom: 18 }}>
        Short triggers that expand into longer phrases while you dictate.
        Say the trigger as a whole word and it'll be replaced before grammar
        correction. Great for email sign-offs, addresses, boilerplate.
      </div>

      <div className="section" style={{
        background: "var(--card-bg)", border: "1px solid var(--card-border)",
        borderRadius: 12, padding: 16,
      }}>
        <div className="stack" style={{ gap: 10 }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="s-trigger">Trigger</label>
            <input id="s-trigger" type="text" value={trigger} placeholder="sig"
                   onChange={(e) => setTrigger(e.target.value)} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="s-exp">Expansion</label>
            <textarea id="s-exp" value={expansion}
                      placeholder="Best regards,&#10;Rounak Lenka"
                      rows={3}
                      onChange={(e) => setExpansion(e.target.value)}
                      style={{
                        width: "100%", padding: "9px 10px",
                        border: "1px solid var(--card-border)", borderRadius: 7,
                        fontSize: 13, background: "#fff", color: "var(--text)",
                        outline: "none", fontFamily: "inherit", resize: "vertical",
                      }} />
          </div>
          <div className="row">
            <button className="btn-primary" onClick={add}
                    disabled={!trigger.trim() || !expansion.trim()}>Add snippet</button>
          </div>
        </div>
        {err && <div className="error-msg">{err}</div>}
      </div>

      <div className="section">
        {entries.length === 0 ? (
          <div className="info-msg">No snippets yet. Add your first one above.</div>
        ) : (
          <div className="history-table">
            {entries.map(([t, v]) => (
              <div key={t} className="history-row" style={{ alignItems: "flex-start" }}>
                <span className="tx" style={{ flex: 0, minWidth: 120, fontWeight: 500, marginTop: 2 }}>{t}</span>
                <span style={{ color: "var(--text-muted)", marginTop: 2 }}>→</span>
                <span className="tx" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v}</span>
                <button className="btn-secondary" onClick={() => remove(t)}
                        style={{ padding: "4px 10px", fontSize: 11, flexShrink: 0 }}>Remove</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
