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
#   GITHUB_REPO=owner/repo  override repo (default: uxie-app/uxie-releases)

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
  # Pick the right workspace member for this host. The Cargo workspace at
  # native-helper/Cargo.toml has both members; we never compile the wrong one
  # (the foreign one's deps wouldn't link anyway).
  case "$(uname -s)" in
    Darwin)                            HELPER_CRATE="helper-mac" ;;
    Linux|MINGW*|MSYS*|CYGWIN*)        HELPER_CRATE="helper-win" ;;
    *) echo "✗ Unsupported host OS: $(uname -s)" >&2; exit 1 ;;
  esac
  echo "  host=$(uname -s)  crate=$HELPER_CRATE"
  (cd "$HELPER_DIR" && cargo build --release -p "$HELPER_CRATE")
  # Binary name is identical across platforms (with .exe suffix on Windows).
  ls -la "$HELPER_DIR/target/release/miniflow-fn-helper"* 2>/dev/null | tail -1
fi

# ── Step 2b: Swift audio-tap (Mac only) ───────────────────────────────────────
# AVCaptureSession + ScreenCaptureKit sidecar. Built into a tiny .app
# sub-bundle (Info.plist inside) so TCC recognises its usage descriptions
# and AVCapture actually delivers buffers (CLI-only binaries silently
# fail). Bundled into Uxie.app via electron-builder mac.extraResources.
#
# Skip via SKIP_AUDIO_TAP=1.

if [ "${SKIP_AUDIO_TAP:-0}" = "1" ]; then
  echo "→ Skipping Swift audio-tap build (SKIP_AUDIO_TAP=1)"
else
  case "$(uname -s)" in
    Darwin)
      echo ""
      echo "━━━ Step 2b: Swift audio-tap ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      AUDIO_TAP_DIR="$SCRIPT_DIR/native-helper/audio-tap"
      if ! command -v swift &>/dev/null; then
        echo "✗ swift command not found — install Xcode command line tools" >&2
        exit 1
      fi
      (cd "$AUDIO_TAP_DIR" && swift build -c release)

      # Assemble the .app sub-bundle around the raw binary so TCC sees a
      # proper Info.plist with our usage descriptions.
      APP_BUNDLE="$AUDIO_TAP_DIR/.build/release/UxieAudioTap.app"
      rm -rf "$APP_BUNDLE"
      mkdir -p "$APP_BUNDLE/Contents/MacOS"
      cp "$AUDIO_TAP_DIR/.build/release/uxie-audio-tap" \
         "$APP_BUNDLE/Contents/MacOS/uxie-audio-tap"
      cp "$AUDIO_TAP_DIR/Resources/Info.plist" "$APP_BUNDLE/Contents/Info.plist"
      ls -la "$APP_BUNDLE/Contents/" "$APP_BUNDLE/Contents/MacOS/"
      ;;
    *)
      # Windows / Linux don't ship the audio tap. The meeting flow falls
      # back to "no audio capture" (Slice 1 status-only flow).
      echo "→ Skipping Swift audio-tap (non-macOS host)"
      ;;
  esac
fi

# ── Step 3: Electron TypeScript + Vite ────────────────────────────────────────

echo ""
echo "━━━ Step 3/4: Electron compile ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Mac-only PATH prepends — Homebrew location for node etc. Harmless on
# Windows (paths just don't exist) but guarding for clarity.
case "$(uname -s)" in
  Darwin)
    export PATH="/opt/homebrew/bin:/opt/homebrew/Cellar/node/24.1.0/bin:/usr/local/bin:$PATH"
    ;;
esac
cd "$ELECTRON_DIR"
if [ "${SKIP_NPM_INSTALL:-0}" != "1" ]; then
  npm install
fi
npm run build

# ── Step 4: electron-builder packaging ────────────────────────────────────────

echo ""
echo "━━━ Step 4/4: electron-builder packaging ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

VERSION=$(node -p "require('./package.json').version")

case "$(uname -s)" in
  Darwin)
    BUILDER_FLAGS="--mac --arm64"
    ARTIFACT_GLOB="$ELECTRON_DIR/dist/Uxie-${VERSION}-arm64.dmg"
    ARTIFACT_LABEL="DMG"
    ;;
  Linux|MINGW*|MSYS*|CYGWIN*)
    BUILDER_FLAGS="--win --x64"
    # electron-builder.yml's win.artifactName resolves to
    # "Uxie-<version>-x64.exe" for the NSIS installer.
    ARTIFACT_GLOB="$ELECTRON_DIR/dist/Uxie-${VERSION}-x64.exe"
    ARTIFACT_LABEL="EXE installer"
    ;;
  *)
    echo "✗ Unsupported host OS for electron-builder: $(uname -s)" >&2
    exit 1
    ;;
esac

echo "  host=$(uname -s)  electron-builder $BUILDER_FLAGS"
npx electron-builder $BUILDER_FLAGS

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  ✓ Build complete"
echo "│  $ARTIFACT_LABEL: $ARTIFACT_GLOB"
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

REPO="${GITHUB_REPO:-uxie-app/uxie-releases}"
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

# Upload artifact via curl with retry + rate limit (large file, flaky Wi-Fi friendly)
UPLOAD_URL=$(gh api "repos/$REPO/releases/tags/$TAG" --jq '.upload_url' | sed 's/{?name,label}//')
TOKEN=$(gh auth token)
DMG="$ARTIFACT_GLOB"   # name kept for backwards compat below; holds DMG on Mac, EXE on Win
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
