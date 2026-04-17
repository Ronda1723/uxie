import React, { useEffect, useState } from "react";
import type { LLMProvider, LLMStatus } from "@shared/types";

type SaveState = "idle" | "saving" | "saved" | "error";

export function ProviderPicker() {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [status, setStatus] = useState<LLMStatus>({});
  const [activeId, setActiveId] = useState<string>("openai");
  const [apiKey, setApiKey] = useState<string>("");
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [save, setSave] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [p, s] = await Promise.all([
        window.miniflow.listProviders(),
        window.miniflow.getLLMStatus(),
      ]);
      setProviders(p);
      setStatus(s);
      const active = (Object.entries(s) as [string, LLMStatus[string]][])
        .find(([, v]) => v.is_active)?.[0] ?? "openai";
      setActiveId(active);
      setBaseUrl(s[active]?.base_url ?? "");
      setModel(s[active]?.model ?? "");
    } catch (e: any) {
      setError(`Could not reach the backend: ${e?.message ?? e}`);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function onSelectProvider(id: string) {
    setActiveId(id);
    setBaseUrl(status[id]?.base_url ?? "");
    setModel(status[id]?.model ?? "");
    setApiKey("");
    setSave("idle"); setError(null);
    try {
      await window.miniflow.setActiveLLM(id);
      await refresh();
    } catch (e: any) {
      setError(`Failed to switch provider: ${e?.message ?? e}`);
    }
  }

  async function onSave() {
    setSave("saving"); setError(null);
    try {
      // Only save the model if the user actually picked one.
      if (model.trim()) {
        await window.miniflow.setLLMModel(activeId, model.trim(), baseUrl.trim() || null);
      }
      if (apiKey.trim()) {
        await window.miniflow.setLLMKey(activeId, apiKey.trim());
        setApiKey("");
      }
      await refresh();
      setSave("saved");
      setTimeout(() => setSave("idle"), 1800);
    } catch (e: any) {
      setSave("error");
      setError(e?.message ?? String(e));
    }
  }

  async function onClearKey() {
    setError(null);
    try {
      await window.miniflow.clearLLMKey(activeId);
      await refresh();
    } catch (e: any) {
      setError(`Could not clear key: ${e?.message ?? e}`);
    }
  }

  const activeMeta = providers.find((p) => p.id === activeId);
  const hasChanges = apiKey.trim().length > 0 || (activeMeta && model.trim() !== status[activeId]?.model);

  return (
    <div className="stack">
      <div>
        <h3>Active provider</h3>
        <div className="chip-row">
          {providers.map((p) => {
            const st = status[p.id];
            const isActive = st?.is_active;
            const isReady = !isActive && st?.configured;
            const cls = `chip ${isActive ? "active" : ""} ${isReady ? "ready" : ""}`.trim();
            return (
              <button key={p.id} className={cls} onClick={() => onSelectProvider(p.id)}
                      title={st?.configured ? "API key saved" : "API key not set"}>
                {p.display_name}
                {isActive && <span className="chip-tag active">active</span>}
                {isReady  && <span className="chip-tag ready">ready</span>}
              </button>
            );
          })}
        </div>
      </div>

      {activeMeta && (
        <>
          <div className="field">
            <label htmlFor="model">Model</label>
            <select id="model" value={model} onChange={(e) => setModel(e.target.value)}>
              {activeMeta.suggested_models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {!activeMeta.suggested_models.includes(model) && model && (
                <option value={model}>{model} (custom)</option>
              )}
            </select>
            <input
              type="text" placeholder="Or type a custom model…"
              value={model} onChange={(e) => setModel(e.target.value)}
              style={{ marginTop: 6 }}
            />
          </div>

          {activeMeta.id === "ollama" && (
            <div className="field">
              <label htmlFor="base">Ollama base URL</label>
              <input id="base" type="text" placeholder="http://localhost:11434"
                     value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
              <div className="info-msg">
                Tool-capable Ollama models: llama3.1, llama3.2, qwen2.5, mistral-nemo.
              </div>
            </div>
          )}

          {activeMeta.requires_key && (
            <div className="field">
              <label htmlFor="key">
                API key {status[activeId]?.configured && <span className="chip-tag ready" style={{ marginLeft: 6 }}>saved</span>}
              </label>
              <input
                id="key" type="password"
                placeholder={status[activeId]?.configured ? "••••••••  (paste a new key to overwrite)" : "paste your API key"}
                value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onSave(); }}
              />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn-secondary" onClick={onClearKey}
                        disabled={!status[activeId]?.configured}>
                  Clear saved key
                </button>
              </div>
              <div className="info-msg">
                Stored in <code>~/miniflow/llm_keys.json</code> (chmod 600).
                Advanced → Reveal keys file to edit by hand.
              </div>
            </div>
          )}

          <div className="row" style={{ marginTop: 6 }}>
            <button
              className="btn-primary"
              onClick={onSave}
              disabled={save === "saving" || !hasChanges}
              title={!hasChanges ? "Change model or paste a key to enable save" : ""}
            >
              {save === "saving" ? "Saving…" : save === "saved" ? "✓ Saved" : "Save"}
            </button>
            {save === "saved" && (
              <span style={{ color: "var(--success-green)", fontSize: 11 }}>
                Key stored — provider is ready.
              </span>
            )}
          </div>
          {error && <div className="error-msg">{error}</div>}
        </>
      )}
    </div>
  );
}
