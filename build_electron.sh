#!/usr/bin/env bash
# build_electron.sh — End-to-end build of the MiniFlow Electron app.
#
# Produces dist/Uxie-<version>-arm64.dmg and publishes to GitHub Releases.
#
# Steps:
#   1. Build the Python backend with PyInstaller (reuses build_backend.sh)
#   2. Build the Rust native helper with cargo --release
#   3. Install Electron deps and compile TS + bundle React with Vite
#   4. Package with electron-builder (pulls in both binaries via extraResources)
#   5. Create GitHub release and upload DMG
#
# Env vars:
#   SKIP_BACKEND=1      skip PyInstaller (reuse existing miniflow-engine/dist)
#   SKIP_HELPER=1       skip cargo build (reuse existing target/release)
#   SKIP_NPM_INSTALL=1  skip npm install (reuse node_modules)
#   SKIP_RELEASE=1      skip GitHub release upload
#   GITHUB_REPO=owner/repo  override repo (default: Ronda1723/Miniflow)

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
  source "$HOME/.cargo/env" 2>/dev/null || export PATH="$HOME/.cargo/bin:$PATH"
  (cd "$HELPER_DIR" && cargo build --release)
  ls -la "$HELPER_DIR/target/release/miniflow-fn-helper"
fi

# ── Step 3: Electron TypeScript + Vite ────────────────────────────────────────

echo ""
echo "━━━ Step 3/4: Electron compile ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
export PATH="/opt/homebrew/bin:/opt/homebrew/Cellar/node/24.1.0/bin:/usr/local/bin:$PATH"
cd "$ELECTRON_DIR"
if [ "${SKIP_NPM_INSTALL:-0}" != "1" ]; then
  npm install
fi
npm run build

# ── Step 4: electron-builder packaging ────────────────────────────────────────

echo ""
echo "━━━ Step 4/4: electron-builder DMG ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
npx electron-builder --mac --arm64

VERSION=$(node -p "require('./package.json').version")
DMG="$ELECTRON_DIR/dist/Uxie-${VERSION}-arm64.dmg"

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  ✓ Build complete"
echo "│  DMG: $DMG"
echo "└─────────────────────────────────────────────────────────┘"
ls -la "$ELECTRON_DIR/dist/" 2>/dev/null || true

# ── Step 5: GitHub release ────────────────────────────────────────────────────

if [ "${SKIP_RELEASE:-0}" = "1" ]; then
  echo "→ Skipping GitHub release (SKIP_RELEASE=1)"
  exit 0
fi

if ! command -v gh &>/dev/null; then
  echo "→ gh CLI not found — skipping release upload"
  exit 0
fi

REPO="${GITHUB_REPO:-Ronda1723/Miniflow}"
TAG="v${VERSION}"

echo ""
echo "━━━ Step 5/5: GitHub release ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "→ Repo: $REPO  Tag: $TAG"

# Create release if it doesn't exist yet
if gh release view "$TAG" --repo "$REPO" &>/dev/null; then
  echo "→ Release $TAG already exists, uploading DMG..."
else
  echo "→ Creating release $TAG..."
  gh release create "$TAG" \
    --repo "$REPO" \
    --title "Uxie $TAG" \
    --notes "Release $TAG"
  echo "→ Release created. Edit notes at: https://github.com/$REPO/releases/tag/$TAG"
  # GitHub needs a moment to settle the release before the upload endpoint accepts large files
  sleep 10
fi

# Upload DMG via curl with retry + rate limit (large file, flaky Wi-Fi friendly)
UPLOAD_URL=$(gh api "repos/$REPO/releases/tags/$TAG" --jq '.upload_url' | sed 's/{?name,label}//')
TOKEN=$(gh auth token)
DMG_NAME="$(basename "$DMG")"

echo "→ Uploading $DMG_NAME ($(du -sh "$DMG" | cut -f1))..."
curl --retry 5 --retry-delay 5 --retry-all-errors \
  --limit-rate 3M \
  -H "Authorization: token $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @"$DMG" \
  "${UPLOAD_URL}?name=${DMG_NAME}" \
  -o /tmp/gh-upload-response.json 2>&1

STATUS=$(python3 -c "import json,sys; d=json.load(open('/tmp/gh-upload-response.json')); print(d.get('state','?'))" 2>/dev/null || echo "unknown")
if [ "$STATUS" = "uploaded" ]; then
  echo "✓ DMG uploaded successfully"
  echo "  Download: https://github.com/$REPO/releases/download/$TAG/$DMG_NAME"
else
  echo "✗ Upload may have failed — check https://github.com/$REPO/releases/tag/$TAG"
  cat /tmp/gh-upload-response.json 2>/dev/null | python3 -m json.tool 2>/dev/null | head -10
fi
