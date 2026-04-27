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
  # Need Python >=3.10 (mcp + several other deps). Apple ships 3.9 as
  # `python3` on stock macOS — too old. Scan a list of known names and
  # known install paths, picking the first that meets the version floor.
  find_python() {
    local candidates=(
      python3.13 python3.12 python3.11 python3.10
      "$HOME/miniconda3/bin/python3.13"
      "$HOME/miniconda3/bin/python3.12"
      /opt/homebrew/bin/python3.13
      /opt/homebrew/bin/python3.12
      /usr/local/bin/python3.13
      /usr/local/bin/python3.12
      python3 python
    )
    for c in "${candidates[@]}"; do
      local cmd
      cmd=$(command -v "$c" 2>/dev/null || ([ -x "$c" ] && echo "$c"))
      [ -z "$cmd" ] && continue
      # Check version: major>3 OR (major==3 AND minor>=10).
      if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    done
    return 1
  }

  PY_BOOTSTRAP=$(find_python) || {
    echo "✗ No Python >= 3.10 found." >&2
    echo "  Install one of:" >&2
    echo "    brew install python@3.13      (macOS)" >&2
    echo "    https://www.python.org/downloads/   (any OS)" >&2
    echo "  Stock macOS Python 3.9 is too old — mcp + several deps require >=3.10." >&2
    exit 1
  }
  echo "→ Creating venv at $VENV using $PY_BOOTSTRAP ($("$PY_BOOTSTRAP" --version 2>&1))"
  "$PY_BOOTSTRAP" -m venv "$VENV"
  # Re-detect bin dir after creation.
  if [ -d "$VENV/Scripts" ]; then VENV_BIN="$VENV/Scripts"; EXE=".exe"; fi
fi

PYTHON="$VENV_BIN/python$EXE"
PIP="$VENV_BIN/pip$EXE"

echo "→ Python: $("$PYTHON" --version)"

# Install requirements if the venv is empty/stale. Cheap to re-run; pip
# is a no-op when everything's already at the pinned version.
#
# IMPORTANT: upgrade pip via `python -m pip`, not the pip executable
# directly. On Windows, pip.exe can't overwrite its own running binary
# and the upgrade fails with "to modify pip, please run python -m pip".
# Same command works on macOS, so we use it everywhere.
echo "→ Ensuring requirements installed..."
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r "$ENGINE_DIR/requirements.txt"
"$PYTHON" -m pip install --quiet --upgrade pyinstaller

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
