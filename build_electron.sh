#!/usr/bin/env bash
# build_electron.sh — End-to-end build of the MiniFlow Electron app.
#
# Produces dist/MiniFlow-<version>.dmg
#
# Steps:
#   1. Build the Python backend with PyInstaller (reuses build_backend.sh)
#   2. Build the Rust native helper with cargo --release
#   3. Install Electron deps and compile TS + bundle React with Vite
#   4. Package with electron-builder (pulls in both binaries via extraResources)
#
# Env vars:
#   SKIP_BACKEND=1    skip PyInstaller (reuse existing miniflow-engine/dist)
#   SKIP_HELPER=1     skip cargo build (reuse existing target/release)
#   SKIP_NPM_INSTALL=1 skip npm install (reuse node_modules)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER_DIR="$SCRIPT_DIR/native-helper"
ELECTRON_DIR="$SCRIPT_DIR/miniflow-electron"
ENGINE_DIR="$SCRIPT_DIR/miniflow-engine"

echo "→ MiniFlow Electron build"
echo "  backend:  $ENGINE_DIR"
echo "  helper:   $HELPER_DIR"
echo "  electron: $ELECTRON_DIR"

# ── Step 1: Python backend ────────────────────────────────────────────────────

if [ "${SKIP_BACKEND:-0}" = "1" ]; then
  echo "→ Skipping backend build (SKIP_BACKEND=1)"
else
  echo ""
  echo "━━━ Step 1/4: PyInstaller bundle ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  bash "$SCRIPT_DIR/build_backend.sh"
fi

# ── Step 2: Rust native helper ────────────────────────────────────────────────

if [ "${SKIP_HELPER:-0}" = "1" ]; then
  echo "→ Skipping helper build (SKIP_HELPER=1)"
else
  echo ""
  echo "━━━ Step 2/4: Rust native helper ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  (cd "$HELPER_DIR" && cargo build --release)
  ls -la "$HELPER_DIR/target/release/miniflow-fn-helper"
fi

# ── Step 3: Electron TypeScript + Vite ────────────────────────────────────────

echo ""
echo "━━━ Step 3/4: Electron compile ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cd "$ELECTRON_DIR"
if [ "${SKIP_NPM_INSTALL:-0}" != "1" ]; then
  npm install
fi
npm run build

# ── Step 4: electron-builder packaging ────────────────────────────────────────

echo ""
echo "━━━ Step 4/4: electron-builder DMG ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
npx electron-builder --mac --arm64

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  ✓ Build complete"
echo "│  DMG: $ELECTRON_DIR/dist/"
echo "└─────────────────────────────────────────────────────────┘"
ls -la "$ELECTRON_DIR/dist/" 2>/dev/null || true
