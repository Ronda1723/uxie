# Migration notes — Swift → Electron + Rust helper (v0.4)

## What changed

| Area | Before (≤ 0.3) | After (0.4) |
|---|---|---|
| Desktop shell | Swift / SwiftUI menu-bar app | Electron + React + TypeScript |
| Hotkey capture | Swift `NSEvent.addGlobalMonitorForEvents` | Rust `CGEventTap` binary (`miniflow-fn-helper`) |
| Synthetic typing | Swift `CGEvent.keyboardSetUnicodeString` | Same API, called from Rust |
| LLM | Hard-coded OpenAI GPT-4o | litellm behind `llm.py` — OpenAI, Anthropic, Gemini, Groq, OpenRouter, Ollama |
| LLM key storage | `~/miniflow/miniflow_keys.json` (chmod 600) | macOS Keychain (`miniflow-llm` service) |
| Hotkey config | Hard-coded Fn | `~/miniflow/hotkey.json` — Fn or any `<mod>+<key>` |
| Build | `build_all.sh` (xcodebuild + PyInstaller + DMG) | `build_electron.sh` (electron-builder + cargo + PyInstaller + DMG) |

## Things that were removed

- The entire `MiniflowApp/` Xcode project.
- `build_all.sh`, `build_dmg.sh` — the Xcode pipeline.
- Direct `openai.AsyncOpenAI` usage in `agent.py`.
- `from openai import AsyncOpenAI` across the backend (kept in `requirements.txt` only because litellm re-uses it under the hood).

## Preserved (zero-change) components

- `miniflow-engine/connectors/` — every provider module works unchanged. The registry and tool-name prefix routing are untouched.
- `miniflow-engine/oauth.py` and the Vercel proxy at `miniflow-auth/`.
- `miniflow-engine/main.py`'s HTTP + WebSocket surface. Swift ↔ Python protocol is now Electron ↔ Python; the wire format is byte-identical.
- `~/miniflow/*` user data: `miniflow_keys.json`, `miniflow_settings.json`, `connectors.json`, `history.json`, `dictionary.json`, `snippets.json`. All continue to load.

## User-visible migration

1. The first time 0.4 runs, it **migrates** any existing `openai` key from `miniflow_keys.json` into the Keychain under `miniflow-llm/openai`. The JSON file is left in place for safety; you can delete it after verifying everything works.
2. The **active provider** defaults to `openai` if that key exists, else no provider is active and commands fall back to plain dictation (same graceful fallback the Swift app had when the OpenAI key was missing).
3. Hotkey: `hotkey.json` is created on first write. Until then the helper uses the default `{mode: hold_to_talk, modifier: fn, key: null}` — identical to the Swift app's behavior.

## Developer migration checklist

- [ ] Install Rust (`curl https://sh.rustup.rs -sSf | sh`) if you didn't have it.
- [ ] Install Node 20+ (`nvm install 20`).
- [ ] Remove any local references to `MiniflowApp/*` from your tooling (e.g. `.vscode/settings.json`).
- [ ] Update any CI scripts that called `build_all.sh` — replace with `build_electron.sh`.
- [ ] The GitHub Actions workflow at `.github/workflows/` still references Swift. Replace with an equivalent job that runs `build_electron.sh` on `macos-14` runners (arm64).

## Unfinished work

The first 0.4 release ships with the agent loop, LLM picker, hotkey recorder, provider picker, and history viewer. Deliberately deferred to later 0.4.x:

- **Integrations tab** — connector OAuth buttons are not yet wired into the Electron UI. Backend endpoints (`start_oauth`, `disconnect_provider`, `get_connected_providers`, `list_connectors`) work; the tab just needs to call them.
- **Dictionary / snippets / styles** — Python module exists and endpoints are wired; no renderer UI yet.
- **Per-connector OAuth test inside the popover** — for now, trigger via the backend's `/invoke/start_oauth`.
- **Universal/Intel dmg** — current `electron-builder.yml` targets arm64 only.
