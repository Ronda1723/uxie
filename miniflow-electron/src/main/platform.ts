// Tiny platform abstraction. Anything OS-specific that the main process
// needs goes through one of these functions so the call sites stay clean
// of `if (process.platform === ...)` ladders.
//
// Supported today:
//   - macOS (darwin)
//   - Windows (win32) — partial; falls back to safe no-ops for things we
//     haven't ported yet (the foreground-app probe, principally)
//
// Not supported:
//   - Linux. We could add it later; not in scope right now.

import { execSync } from "node:child_process";

export const IS_MAC = process.platform === "darwin";
export const IS_WIN = process.platform === "win32";

/** Hide the dock icon (macOS only — Windows has no dock). */
export function hideDockIcon(app: Electron.App): void {
  if (IS_MAC) app.dock?.hide();
}

/**
 * Pin a window so it floats above everything — full-screen apps, screen
 * savers, etc. macOS uses the "screen-saver" level and a Spaces flag so
 * the window follows the user across desktops; Windows just needs plain
 * alwaysOnTop (no Spaces equivalent and the level enum is mac-only).
 */
export function makeOverlayFloatTop(win: Electron.BrowserWindow): void {
  if (IS_MAC) {
    win.setAlwaysOnTop(true, "screen-saver");
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  } else {
    win.setAlwaysOnTop(true);
  }
}

/**
 * Bundle ID / executable name of the foreground app.
 *
 * On macOS we ask System Events via osascript — fast and reliable.
 *
 * On Windows we'd need GetForegroundWindow + GetWindowThreadProcessId +
 * QueryFullProcessImageName via a native binding (or shell out to PowerShell).
 * Both add a process spawn per hotkey press; deferring the real impl until
 * we actually need it on Windows. Until then, returns null and the agent
 * falls back to "no target app context" — dictation still works fine.
 *
 * Returns null on any error so callers don't have to wrap.
 */
export function getFrontmostAppId(): string | null {
  if (IS_MAC) {
    try {
      return execSync(
        `osascript -e 'tell application "System Events" to get bundle identifier of (first process whose frontmost is true)'`,
        { timeout: 500, encoding: "utf8" }
      ).trim() || null;
    } catch {
      return null;
    }
  }
  // TODO(windows): use a native binding (active-win, or a Win32 FFI) to
  // return the foreground process name. Returning null is safe — the agent
  // treats it as "no target app context" which means most things still work.
  return null;
}
