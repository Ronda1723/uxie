#!/usr/bin/env bash
# Uxie installer — downloads the latest signed DMG from GitHub Releases,
# copies it to /Applications, and strips the Gatekeeper quarantine flag.
#
# Run with:
#   curl -fsSL https://raw.githubusercontent.com/uxie-app/uxie-releases/main/install.sh | bash
#
# Until Uxie has a notarized build (Apple Developer account pending), this
# script is the smoothest way to install — it's the exact same thing the
# right-click → Open flow does manually.

set -euo pipefail

REPO="uxie-app/uxie-releases"
APP_NAME="Uxie"

say()  { printf "\033[1;36m→ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

# ── Preflight ────────────────────────────────────────────────────────────────

[ "$(uname)" = "Darwin" ] || die "Uxie is macOS-only (you're on $(uname))."
ARCH=$(uname -m)
[ "$ARCH" = "arm64" ] || die "Uxie currently ships Apple Silicon only (you're on $ARCH)."

for cmd in curl hdiutil xattr; do
  command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd"
done

# ── Discover latest release ──────────────────────────────────────────────────

say "Finding latest ${APP_NAME} release…"
# Public releases don't need auth; fall back gracefully if rate-limited.
API_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null) \
  || die "Could not reach GitHub. Check your internet or try again in a minute."

DMG_URL=$(printf '%s' "$API_JSON" \
  | grep -oE 'https://[^"]+-arm64\.dmg' \
  | head -n1)

[ -n "$DMG_URL" ] || die "No arm64 DMG found in the latest release."
VERSION=$(printf '%s' "$API_JSON" | grep -oE '"tag_name": *"[^"]+"' | head -n1 | cut -d'"' -f4)

say "Installing ${APP_NAME} ${VERSION:-latest}"

# ── Download ─────────────────────────────────────────────────────────────────

TMP=$(mktemp -d -t uxie-install)
trap 'rm -rf "$TMP"; hdiutil detach "$MOUNT" -quiet 2>/dev/null || true' EXIT

DMG="$TMP/${APP_NAME}.dmg"
say "Downloading…"
curl --fail --location --progress-bar "$DMG_URL" -o "$DMG"

# ── Mount ────────────────────────────────────────────────────────────────────

say "Mounting…"
MOUNT=$(hdiutil attach "$DMG" -nobrowse -readonly -mountrandom "$TMP" \
  | awk -F'\t' 'END{gsub(/^ +/, "", $NF); print $NF}')

[ -d "$MOUNT" ] || die "DMG didn't mount — it may be corrupt. Re-run the installer."

APP_SRC=$(ls -d "$MOUNT"/*.app 2>/dev/null | head -n1)
[ -n "$APP_SRC" ] || die "No .app bundle found inside the DMG."

# ── Install ──────────────────────────────────────────────────────────────────

DEST="/Applications/$(basename "$APP_SRC")"

if [ -d "$DEST" ]; then
  say "Removing existing install at $DEST"
  # Best-effort quit; no drama if it wasn't running.
  osascript -e "tell application \"${APP_NAME}\" to quit" >/dev/null 2>&1 || true
  sleep 1
  rm -rf "$DEST"
fi

say "Copying to /Applications…"
cp -R "$APP_SRC" /Applications/

# ── Strip Gatekeeper quarantine ──────────────────────────────────────────────
# Exactly what right-click → Open does. Required until the build is notarized.

say "Clearing quarantine flag…"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

# ── Done ─────────────────────────────────────────────────────────────────────

ok "${APP_NAME} ${VERSION:-} installed."
echo ""
echo "  Launch:   open \"$DEST\""
echo "  Or find '${APP_NAME}' in your Applications folder."
echo ""
echo "  First launch will ask for Microphone, Accessibility, and Input Monitoring"
echo "  permissions — grant all three for dictation + hotkey to work."
