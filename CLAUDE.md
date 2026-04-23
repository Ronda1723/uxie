# Uxie — Claude Code Context

## What this is
Uxie is a voice-powered macOS desktop agent. Users speak → Uxie dictates or runs agentic commands. Stack: Electron (TypeScript/React) + Python FastAPI engine (PyInstaller bundle) + Rust native helper + Railway FastAPI backend.

## Repo layout
```
miniflow-electron/   Electron shell (TypeScript + React + Vite)
miniflow-engine/     Python backend (runs locally as PyInstaller binary)
native-helper/       Rust hotkey/accessibility helper
uxie-backend/        Railway cloud backend (auth + API proxy)
build_electron.sh    Full build + GitHub release script
build_backend.sh     PyInstaller-only build
```

## CRITICAL: All API calls go through the Railway backend

**Never** add user-facing API key inputs. Users log in with email/OTP → get JWT → everything works.

### STT (Deepgram)
- `miniflow-engine/audio.py` calls `POST https://uxie-production.up.railway.app/stt/session` with JWT
- Backend returns the server-side Deepgram key
- App connects to Deepgram WebSocket directly using that key
- Railway env var: `DEEPGRAM_API_KEY`

### LLM
- Default active provider in `miniflow-engine/config.py` is `"uxie"`
- `miniflow-engine/llm.py` routes `uxie` provider → Railway `/llm/stream` (SSE) or `/llm/chat` (tool-calling)
- Railway proxies to Groq (dictation) or OpenAI (commands) using server-side keys
- Railway env vars: `GROQ_API_KEY`, `OPENAI_API_KEY`

### What breaks this rule
- Setting default active provider to anything other than `"uxie"` in `config.py`
- Adding API key fields to `SettingsModal.tsx`
- Calling Deepgram/Groq/OpenAI directly from `audio.py` or `agent.py`

## GitHub + releases
- **Only repo**: `Ronda1723/uxie` — never push to `Ronda1723/Miniflow`
- Branch: `uxie-init`
- Build + release: `bash build_electron.sh` (publishes DMG to GitHub Releases)

## Railway backend
- URL: `https://uxie-production.up.railway.app`
- Source: `uxie-backend/` directory
- Required env vars: `DEEPGRAM_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `RESEND_API_KEY`, `DATABASE_URL`

## Key files
- `miniflow-engine/audio.py` — STT pipeline (Deepgram WebSocket)
- `miniflow-engine/agent.py` — LLM agent loop, grammar correction
- `miniflow-engine/llm.py` — LLM provider abstraction (uxie = Railway proxy)
- `miniflow-engine/config.py` — config + JWT storage, default provider = "uxie"
- `miniflow-engine/normalize.py` — email/URL spoken-word normalization
- `miniflow-electron/src/main/overlayWindow.ts` — floating approval overlay
- `miniflow-electron/src/renderer/components/OverlayWidget.tsx` — overlay UI
- `uxie-backend/proxy.py` — `/llm/stream`, `/llm/chat`, `/stt/session` endpoints
- `uxie-backend/auth.py` — OTP send/verify, JWT issue

## Google OAuth credentials
- Stored in `miniflow-engine/oauth.py` (never commit real values — use env vars or local-only file)
- Client ID: `1020071381286-d5fnq752smjho5ickcea67bmgg86kbjc.apps.googleusercontent.com`
- Secret: stored locally only, not in git
