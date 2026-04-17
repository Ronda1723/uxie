# MiniFlow

Voice-powered desktop agent for macOS. Hold your hotkey (default: **Fn**) to speak — MiniFlow transcribes, understands, and acts.

---

## What it does

- **Voice commands** — "Send a Slack message to John saying I'll be late" → done
- **Dictation** — hold the hotkey anywhere, speak, release — text is typed at your cursor
- **App integrations** — Slack, Gmail, Google Calendar, GitHub, Notion, Linear, Jira, Spotify, Discord
- **Any LLM** — OpenAI, Anthropic, Gemini, Groq, OpenRouter, or local Ollama — you pick
- **Always available** — lives in your menu bar, no window to manage

---

## Architecture (v0.4 and later)

```
┌────────────────────┐   child_process.spawn    ┌────────────────────┐
│  Electron main     │ ───────────────────────▶ │  Python backend    │
│  (Node.js)         │ ◀─── WebSocket /ws ───── │  (FastAPI :8765)   │
│                    │ ───  HTTP  /invoke ────▶ │                    │
│                    │                          │  connectors/ …     │
│  Rust native       │                          │  llm.py (litellm)  │
│  helper via stdin/ │                          │                    │
│  stdout (hotkey)   │                          │                    │
└────────────────────┘                          └────────────────────┘
         ▲
         │
    macOS menu bar tray + popover UI (React)
```

Three independent pieces, each testable on its own:

| Component | Stack | Where |
|---|---|---|
| Desktop shell | Electron + TypeScript + React | [`miniflow-electron/`](miniflow-electron/) |
| Native hotkey + typing helper | Rust (`CGEventTap`) | [`native-helper/`](native-helper/) |
| Agent + STT + connectors | Python + FastAPI + litellm | [`miniflow-engine/`](miniflow-engine/) |
| OAuth proxy | Node.js on Vercel | [`miniflow-auth/`](miniflow-auth/) |

The previous Swift/SwiftUI shell has been retired.

---

## Prerequisites

| Requirement | Minimum |
|---|---|
| macOS | Ventura 13.0 or later |
| Architecture | Apple Silicon (arm64) |
| Node.js | 20.x LTS |
| Rust | 1.75 or later |
| Python | 3.10+ (only for building from source) |

---

## Installation (from DMG)

1. Open the DMG and drag **MiniFlow.app** into **Applications**.
2. Run once, from Terminal, to clear the Gatekeeper quarantine flag:
   ```bash
   xattr -cr /Applications/MiniFlow.app && open /Applications/MiniFlow.app
   ```
3. On first launch, macOS will ask for:
   - **Microphone** — voice input
   - **Input Monitoring** — hotkey detection (the Rust helper needs this)
   - **Accessibility** — typing dictated text into the frontmost app

Re-enable any denied permission under **System Settings → Privacy & Security**.

---

## Pick your LLM

Open the MiniFlow popover → **LLM Providers** tab. Pick a provider, paste your API key, pick a model, click Save. Keys are stored in the macOS Keychain (service `miniflow-llm`).

| Provider | Key source |
|---|---|
| OpenAI | [platform.openai.com](https://platform.openai.com) |
| Anthropic | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) |
| Groq | [console.groq.com](https://console.groq.com) |
| OpenRouter | [openrouter.ai](https://openrouter.ai) |
| Ollama (local) | No key — install [ollama.com](https://ollama.com) and pull a tool-capable model |

**Ollama tool-capable models:** `llama3.1`, `llama3.2`, `qwen2.5`, `mistral-nemo`. The model picker warns you if you pick one that won't work.

You still need a **Smallest AI** key for speech-to-text ([waves.smallest.ai](https://waves.smallest.ai)).

---

## Customize the hotkey

Open **Hotkey** tab:

- **Fn (default)** — hold-to-talk. Works exactly as before.
- **Custom:** click the recorder, press any `<modifier> + <key>` combination (e.g. ⌘ + Space, ⌥ + D). Pick **Hold to talk** or **Press to toggle** mode.

Config lives in `~/miniflow/hotkey.json`. The Rust helper re-reads it on `SIGHUP` so changes apply instantly.

---

## Usage

| Action | Result |
|---|---|
| **Hold Fn** (or your hotkey) | Start listening |
| **Release Fn** | Stop — command is processed |
| **Click menu bar icon** | Open / close the settings popover |
| **Right-click menu bar** | Quit |

### Example commands

- "Draft an email to Sarah about the project update"
- "Create a GitHub issue: login page is broken"
- "Add a task in Linear: refactor auth module, high priority"
- "Play something relaxing on Spotify"
- "What's on my calendar tomorrow?"

---

## Connecting integrations

**LLM Providers** tab configures the model.
**(Future)** Integrations tab connects your Slack / Gmail / etc. via OAuth. Until the Electron integrations UI lands, use the Python backend's `start_oauth` endpoint directly:

```bash
curl -X POST http://127.0.0.1:8765/invoke/start_oauth \
  -H "Content-Type: application/json" \
  -d '{"provider":"slack"}'
```

Supported: Slack · Gmail · Google Calendar · Google Drive · GitHub · Notion · Linear · Jira · Spotify · Discord.

---

## Building from source

```bash
git clone https://github.com/Ronda1723/Miniflow.git
cd Miniflow

# One-shot build: PyInstaller + cargo + electron-builder → DMG
./build_electron.sh
```

Output: `miniflow-electron/dist/MiniFlow-0.4.0.dmg`.

Env-var knobs: `SKIP_BACKEND=1`, `SKIP_HELPER=1`, `SKIP_NPM_INSTALL=1`.

### Dev mode (no DMG, no packaging)

```bash
# Terminal 1 — Python backend
cd miniflow-engine && ./venv/bin/python main.py

# Terminal 2 — Rust helper (separate so you can see its logs)
cd native-helper && cargo build --release
./target/release/miniflow-fn-helper        # not strictly needed; Electron spawns it

# Terminal 3 — Electron dev server + main watcher
cd miniflow-electron && npm run dev
# in another tab:
cd miniflow-electron && MINIFLOW_ENGINE_EXTERNAL=1 npm start
```

---

## Running the tests

```bash
# Python agent + config + hotkey + connectors  (43 tests)
cd miniflow-engine && env -u SSL_CERT_FILE -u REQUESTS_CA_BUNDLE \
  ./venv/bin/python -m pytest tests/ -v

# Rust native helper                           (6 tests)
cd native-helper && cargo test

# Electron renderer + main-process unit tests  (22 tests)
cd miniflow-electron && npm test

# Electron end-to-end (requires a built app + backend)
cd miniflow-electron && npm run build && npm run test:e2e
```

See [TESTING.md](TESTING.md) for the full UI + functional test plan.

---

## Troubleshooting

**App doesn't respond to the hotkey**
→ Check **Input Monitoring** (for the helper) and **Accessibility** (for typing) in System Settings → Privacy & Security. The helper writes its PID to `~/miniflow/miniflow-fn-helper.pid`.

**Transcription never starts**
→ Check Microphone permission. Verify your Smallest AI key is set (Settings → LLM Providers is only about the agent LLM; STT is separate).

**"Engine failed to start"**
→ Tail the log: `tail -f ~/miniflow/miniflow.log`. Usually an expired API key or a network block on `localhost:8765`.

**Model refuses to call tools (Ollama)**
→ You picked a model without tool-calling support. Use one of: `llama3.1`, `llama3.2`, `qwen2.5`, `mistral-nemo`.

**Logs**
```bash
tail -f ~/miniflow/miniflow.log
```
