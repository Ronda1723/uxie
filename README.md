# Uxie

Voice-powered desktop agent. Hold a hotkey, speak — Uxie transcribes, understands, and acts.

- macOS · hold **Fn**
- Windows · hold **Right-Alt** (`fn` is firmware-level on Windows laptops and not interceptable)

> Source is private (`uxie-app/uxie`). Installers + DMGs/EXEs are published to the public [`uxie-app/uxie-releases`](https://github.com/uxie-app/uxie-releases).

---

## What it does

- **Dictation** — hold the hotkey anywhere, speak, release. Grammar-corrected text appears at your cursor.
- **Voice commands** — *"send a Slack message to John saying I'll be late"*, *"what's on my calendar tomorrow?"*, *"open my Downloads folder"*. Routed through tool-calling LLMs.
- **App connectors** — Slack · Gmail · Google Calendar · Drive · GitHub · Notion · Linear · Jira · Spotify · Discord
- **Always available** — lives in your menu bar / system tray, no window to manage

---

## Install

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/uxie-app/uxie-releases/main/install.sh | bash
```

The script downloads the latest signed DMG, copies Uxie to `/Applications`, and clears Gatekeeper's quarantine flag (Uxie is signed but not yet Apple-notarized — that ships with the new Apple Developer account).

Manual fallback or full install instructions: [INSTALL.md](INSTALL.md).

### Windows

Download `Uxie-<version>-x64.exe` from the [latest release](https://github.com/uxie-app/uxie-releases/releases/latest), run it, accept the SmartScreen warning ("More info → Run anyway" — the build isn't Authenticode-signed yet).

> ⚠️ Apple-notarization on macOS and Authenticode signing on Windows are both deliberately deferred. Both add per-year cert costs and a verification flow that we'll adopt before public launch. Until then, the install scripts above handle the Gatekeeper / SmartScreen friction.

---

## First launch

You'll be asked for permissions. **Grant all of them** or the hotkey won't work:

| Permission | Why |
|---|---|
| **Microphone** | record dictation audio |
| **Accessibility** *(macOS)* | type the transcript into the focused app |
| **Input Monitoring** *(macOS)* | detect the global Fn key |

On Windows, the equivalent prompts (mic + accessibility-style global hook permission) come up the first time you press Right-Alt.

After installing, sign in with your email (Uxie sends a 6-digit OTP via email; no passwords). The JWT is written to `~/miniflow/uxie_auth.json` (mode `0600` — owner read/write only) and the engine reads it on every backend call. All STT and LLM calls go through Uxie's Railway backend — **no API keys to configure**.

> **Backlog item**: move JWT into the OS keychain (Keychain on macOS, Credential Manager / DPAPI on Windows). Plaintext-on-disk is fine for the beta but wrong as a long-term default. The [`keyring`](https://pypi.org/project/keyring/) helpers in `config.py` are already wired for the legacy LLM-key model — extending them to JWT storage is a small refactor.

---

## Architecture

```text
       ┌────────────────────┐                   ┌────────────────────┐
       │  Electron main     │   spawn (stdio)   │  Python engine     │
       │  (TypeScript)      │ ─────────────────▶│  (FastAPI :8765,   │
       │  ◀──── ws ───────  │ ◀── ws  /ws ─────│   PyInstaller bin) │
       └─────┬──────────────┘                   └─────────┬──────────┘
             │ spawn (stdio)                              │ HTTPS + JWT
             ▼                                            ▼
       ┌────────────────────┐                   ┌────────────────────┐
       │  Rust helper       │                   │  Railway backend   │
       │  (hotkey + typing) │                   │  (auth + LLM proxy │
       │   helper-mac /     │                   │   + STT key mint   │
       │   helper-win       │                   │   + admin)         │
       └────────────────────┘                   └─────────┬──────────┘
                                                          │  server-side
                                                          ▼  master keys
                                          Deepgram · OpenAI · Groq
```

| Component | Stack | Where |
|---|---|---|
| Desktop shell | Electron + TypeScript + React + Vite | [`miniflow-electron/`](miniflow-electron/) |
| Native hotkey + typing helper (Cargo workspace) | Rust | [`native-helper/helper-mac/`](native-helper/helper-mac/) · [`native-helper/helper-win/`](native-helper/helper-win/) |
| Local agent + STT pipeline + connectors | Python + FastAPI + litellm | [`miniflow-engine/`](miniflow-engine/) |
| Cloud backend (auth, LLM/STT proxy, admin dashboard) | Python + FastAPI on Railway | [`uxie-backend/`](uxie-backend/) |

**Critical architectural rule** — see [`CLAUDE.md`](CLAUDE.md): the desktop app **never holds Deepgram / OpenAI / Groq master keys**. They live only in Railway env vars. Two flows that respect that rule:

- **LLM** is fully proxied: client → Railway (`/llm/stream`, `/llm/chat`) → provider. Audio bytes / prompts travel through Railway.
- **STT** uses an ephemeral-key handshake: client asks Railway (`/stt/session`) → gets a 5-minute scoped Deepgram key → opens the audio WebSocket *directly* to `wss://api.deepgram.com/v1/listen` with that key. Master Deepgram key never leaves Railway; the audio doesn't double-hop through us.

---

## Build from source

### Prerequisites (any platform)

| Tool | Version |
|---|---|
| Node | 20 LTS |
| Python | 3.10 or newer (stock macOS 3.9 is too old for `mcp`) |
| Rust | stable (`rustup default stable`) |
| Git | any recent |

**macOS additionally:** Xcode command-line tools (`xcode-select --install`).
**Windows additionally:** Visual Studio Build Tools 2022 with **Desktop development with C++** workload (Rust + native module compilation).

### Build the whole stack

```bash
git clone https://github.com/uxie-app/uxie.git
cd uxie
bash build_electron.sh
```

This script auto-detects the host OS via `uname -s` and:

1. Bootstraps `miniflow-engine/venv` if missing, installs `requirements.txt`, runs PyInstaller → `miniflow-engine/dist/miniflow-engine/`
2. Builds the right Rust crate (`helper-mac` on Darwin, `helper-win` on MINGW/MSYS/CYGWIN) → `native-helper/target/release/miniflow-fn-helper(.exe)`
3. Compiles the Electron renderer + main → `miniflow-electron/build/`
4. Packages with `electron-builder` → `miniflow-electron/dist/Uxie-<version>-arm64.dmg` *(macOS)* or `Uxie-<version>-x64.exe` *(Windows NSIS installer)*
5. Optionally creates / uploads to a GitHub Release in `uxie-app/uxie-releases`

### Skip-flags for incremental builds

```bash
SKIP_BACKEND=1 SKIP_HELPER=1 SKIP_NPM_INSTALL=1 SKIP_RELEASE=1 bash build_electron.sh
```

### Dev mode (no DMG / EXE, hot-reloading UI)

**macOS / Linux:**

```bash
# Terminal 1 — Python engine
cd miniflow-engine && ./venv/bin/python main.py

# Terminal 2 — Electron + Vite watcher
cd miniflow-electron && npm run dev
# in another tab:
cd miniflow-electron && MINIFLOW_ENGINE_EXTERNAL=1 npm start
```

**Windows (PowerShell or Git Bash):**

```powershell
# Terminal 1 — Python engine
cd miniflow-engine
.\venv\Scripts\python.exe main.py

# Terminal 2 — Electron + Vite watcher
cd miniflow-electron
npm run dev
# in another tab:
cd miniflow-electron
$env:MINIFLOW_ENGINE_EXTERNAL = "1"; npm start
```

The Rust helper is built once with `cargo build --release -p helper-mac` (macOS) or `cargo build --release -p helper-win` (Windows) — Electron spawns it from `native-helper/target/release/`.

---

## CI

`.github/workflows/build.yml` runs on `workflow_dispatch`:

- `build-macos` — macOS-14 arm64 runner → produces `Uxie-<version>-arm64.dmg`
- `build-windows` — windows-latest x64 runner → produces `Uxie-<version>-x64.exe`

Both upload as workflow artifacts. CI builds are intentionally **unsigned** (no Developer ID cert / Authenticode cert in the runners yet); local `build_electron.sh` runs are signed via your Keychain.

---

## Usage

| Action | Result |
|---|---|
| **Hold** *Fn (mac) / Right-Alt (win)* | Start listening |
| **Release** | Stop — transcript is corrected and typed |
| **Click menu-bar / tray icon** | Open / close the popover |
| **Right-click menu-bar / tray icon** | Quit |

### Example commands

- "Draft an email to Sarah about the project update"
- "Create a GitHub issue: login page is broken"
- "Add a task in Linear: refactor auth module, high priority"
- "What's on my calendar tomorrow?"
- "Open my Downloads folder"

---

## Tests

**macOS / Linux:**

```bash
# Python engine (agent + connectors + config)
cd miniflow-engine && ./venv/bin/python -m pytest tests/ -v

# Rust helper
cd native-helper && cargo test -p helper-mac

# Electron renderer + main unit tests
cd miniflow-electron && npm test

# Backend (Railway code)
cd uxie-backend && pytest
```

**Windows (PowerShell):**

```powershell
# Python engine
cd miniflow-engine
.\venv\Scripts\python.exe -m pytest tests/ -v

# Rust helper
cd native-helper
cargo test -p helper-win

# Electron + backend (same as Unix)
cd ..\miniflow-electron; npm test
cd ..\uxie-backend;     .\venv\Scripts\python.exe -m pytest
```

---

## Troubleshooting

**Hotkey does nothing after install (macOS)**
→ System Settings → Privacy & Security → **Input Monitoring** AND **Accessibility** — toggle Uxie ON in both. Macros and re-installs reset these.

**"Damaged, move to trash" warning on macOS**
→ Pre-notarization. Run `xattr -dr com.apple.quarantine /Applications/Uxie.app`.

**SmartScreen warning on Windows**
→ Pre-Authenticode-signing. Click "More info → Run anyway."

**No transcript appearing**
→ `tail -f ~/miniflow/miniflow.log` (macOS) or `%LOCALAPPDATA%\Uxie\logs\miniflow.log` (Windows). The signals to look for, in order:
> 1. `POST .../stt/session "HTTP/1.1 200"` — Railway minted an ephemeral Deepgram key. If this is missing or non-200, the JWT may have expired (re-sign in via email OTP).
> 2. `Deepgram connected (sample_rate=16000)` — engine opened the audio WebSocket directly to Deepgram with that key. Per the architectural rule, audio bytes do not go through Railway; only the master key stays server-side.
> 3. `Deepgram final raw (...)` lines — actual transcripts coming back. If steps 1+2 succeed but step 3 is empty / says "did not receive audio", the mic isn't being captured (permission issue or wrong input device).

**Engine fails to start**
→ Check the same log. Most common: an OS-update reset Python permissions, or the JWT in `~/miniflow/uxie_auth.json` expired (re-sign in via email OTP).

**Windows installer hangs mid-way**
→ Likely antivirus quarantining the bundled PyInstaller binary. Open Windows Security → Protection History — whitelist `Uxie.exe` and `miniflow-engine.exe` and re-run.

---

## Status & roadmap

**Stable today (macOS):** dictation, commands, app connectors, admin dashboard, audio + transcript debug logging.

**Stable today (Windows):** dictation, commands, basic typing. Frontmost-app detection (used for context-aware commands like "send to John") falls back to no-context mode — UI Automation port is the next Windows-side milestone.

**Backlog:**
- Apple notarization pipeline (post Apple Developer account approval)
- Authenticode code-signing for Windows
- macOS auto-update (`electron-updater`)
- Type-and-backspace marked-text injection (live in-app transcript updates)
- Per-user audio-recording opt-in toggle (currently always on for debugging)
- Google OAuth verification (for public Calendar/Gmail-readonly access)
- Path A → C of the macOS-dictation-quality UX work (see `CLAUDE.md`)

---

## License

Private. All rights reserved by Uxie Labs.
