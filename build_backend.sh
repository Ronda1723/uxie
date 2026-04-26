#!/usr/bin/env bash
# build_backend.sh — Bundle the Python backend into a directory bundle.
# Uses the project venv so no system Python dependencies are needed.
#
# Output: miniflow-engine/dist/miniflow-engine/  (directory, ~80 MB)
# The executable is: dist/miniflow-engine/miniflow-engine
#
# Using --onedir (not --onefile) so the engine launches instantly without
# a slow /tmp extraction step on every run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$SCRIPT_DIR/miniflow-engine"
VENV="$ENGINE_DIR/venv"

# ── Bootstrap venv ────────────────────────────────────────────────────────────
# Create the venv on demand. Lets `bash build_backend.sh` work in three
# environments without extra setup steps:
#   - Local dev (venv usually exists, gets reused as-is)
#   - Fresh clone (creates venv + installs requirements)
#   - CI runners (no prior state — same as fresh clone)

# PyInstaller drops platform-specific binaries into bin/ on POSIX and
# Scripts/ on Windows. Detect once, reuse.
if [ -d "$VENV/Scripts" ]; then
  VENV_BIN="$VENV/Scripts"
  EXE=".exe"
else
  VENV_BIN="$VENV/bin"
  EXE=""
fi

if [ ! -d "$VENV" ]; then
  echo "→ Creating venv at $VENV"
  # Prefer python3, fall back to python on systems where the unsuffixed name
  # is the modern interpreter (Windows, some CI images).
  PY_BOOTSTRAP="$(command -v python3 || command -v python)"
  [ -n "$PY_BOOTSTRAP" ] || { echo "✗ no python3 / python on PATH"; exit 1; }
  "$PY_BOOTSTRAP" -m venv "$VENV"
  # Re-detect bin dir after creation.
  if [ -d "$VENV/Scripts" ]; then VENV_BIN="$VENV/Scripts"; EXE=".exe"; fi
fi

PYTHON="$VENV_BIN/python$EXE"
PIP="$VENV_BIN/pip$EXE"

echo "→ Python: $("$PYTHON" --version)"

# Install requirements if the venv is empty/stale. Cheap to re-run; pip
# is a no-op when everything's already at the pinned version.
echo "→ Ensuring requirements installed..."
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -r "$ENGINE_DIR/requirements.txt"
"$PIP" install --quiet --upgrade pyinstaller

PYINSTALLER="$VENV_BIN/pyinstaller$EXE"

# ── Bundle ────────────────────────────────────────────────────────────────────

echo "→ Bundling miniflow-engine..."
cd "$ENGINE_DIR"

# pyobjc_framework_* are macOS-only — PyInstaller errors out with
# 'module not found' if we pass them on Windows / Linux.
PLATFORM_ARGS=()
case "$(uname -s)" in
  Darwin)
    PLATFORM_ARGS+=(--collect-all "pyobjc_framework_Quartz")
    PLATFORM_ARGS+=(--collect-all "pyobjc_framework_AppKit")
    ;;
esac

"$PYINSTALLER" \
  --onedir \
  --name miniflow-engine \
  --hidden-import "uvicorn.logging" \
  --hidden-import "uvicorn.loops.auto" \
  --hidden-import "uvicorn.lifespan.on" \
  --hidden-import "uvicorn.protocols.http.auto" \
  --hidden-import "uvicorn.protocols.websockets.auto" \
  --hidden-import "mcp" \
  --hidden-import "mcp.client.stdio" \
  --hidden-import "mcp.types" \
  --hidden-import "connectors.registry" \
  --collect-all "tiktoken" \
  --collect-all "tiktoken_ext" \
  --collect-all "litellm" \
  --collect-all "mcp" \
  --hidden-import "tiktoken_ext" \
  --hidden-import "tiktoken_ext.openai_public" \
  "${PLATFORM_ARGS[@]}" \
  --noconfirm \
  main.py

echo ""
echo "✓ Bundle ready: $ENGINE_DIR/dist/miniflow-engine/"
echo "  Executable:   $ENGINE_DIR/dist/miniflow-engine/miniflow-engine"
