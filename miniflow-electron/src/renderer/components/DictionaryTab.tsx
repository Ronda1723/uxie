import React, { useEffect, useState } from "react";

export function DictionaryTab() {
  const [dict, setDict] = useState<Record<string, string>>({});
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const d = (await (window.miniflow as any).getDictionary()) as Record<string, string>;
      setDict(d || {});
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }

  useEffect(() => { refresh(); }, []);

  async function add() {
    if (!from.trim() || !to.trim()) return;
    try {
      await (window.miniflow as any).addDictWord(from.trim(), to.trim());
      setFrom(""); setTo(""); setErr(null);
      await refresh();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    }
  }
  async function remove(word: string) {
    await (window.miniflow as any).removeDictWord(word);
    await refresh();
  }

  const entries = Object.entries(dict).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="home">
      <h1>Dictionary</h1>
      <div className="info-msg" style={{ marginBottom: 18 }}>
        Words the STT model tends to mis-hear. Entries apply to every transcript
        before grammar correction. Case-insensitive; matched on whole-word boundaries.
        Example: map <code>gitub</code> → <code>GitHub</code>, <code>ny</code> → <code>NYC</code>.
      </div>

      <div className="section" style={{
        background: "var(--card-bg)", border: "1px solid var(--card-border)",
        borderRadius: 12, padding: 16,
      }}>
        <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="field" style={{ flex: 1, minWidth: 160, marginBottom: 0 }}>
            <label htmlFor="d-from">When you say</label>
            <input id="d-from" type="text" value={from} placeholder="gitub"
                   onChange={(e) => setFrom(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
          </div>
          <div style={{ alignSelf: "center", paddingBottom: 8, color: "var(--text-muted)" }}>→</div>
          <div className="field" style={{ flex: 1, minWidth: 160, marginBottom: 0 }}>
            <label htmlFor="d-to">Write it as</label>
            <input id="d-to" type="text" value={to} placeholder="GitHub"
                   onChange={(e) => setTo(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
          </div>
          <button className="btn-primary" onClick={add}
                  disabled={!from.trim() || !to.trim()}>Add</button>
        </div>
        {err && <div className="error-msg">{err}</div>}
      </div>

      <div className="section">
        {entries.length === 0 ? (
          <div className="info-msg">No entries yet. Add your first mapping above.</div>
        ) : (
          <div className="history-table">
            {entries.map(([k, v]) => (
              <div key={k} className="history-row">
                <span className="tx" style={{ flex: 0, minWidth: 160, fontWeight: 500 }}>{k}</span>
                <span style={{ color: "var(--text-muted)" }}>→</span>
                <span className="tx">{v}</span>
                <button className="btn-secondary" onClick={() => remove(k)}
                        style={{ padding: "4px 10px", fontSize: 11 }}>Remove</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
