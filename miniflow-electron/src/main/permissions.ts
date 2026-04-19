// macOS permission status + request wrappers.
//
// - Microphone: fully automatic via systemPreferences.askForMediaAccess.
// - Accessibility: programmatic prompt via isTrustedAccessibilityClient(true).
// - Input Monitoring: macOS exposes no "request" API. Best we can do is open
//   the exact System Settings pane and highlight our helper binary.

import { systemPreferences, shell, app } from "electron";
import path from "node:path";
import fs from "node:fs";

export type PermissionId = "microphone" | "accessibility" | "inputMonitoring";
export type PermissionStatus = "granted" | "denied" | "not-determined" | "unknown";

export interface PermissionState {
  id: PermissionId;
  status: PermissionStatus;
  canAutoRequest: boolean;
  hint: string;
}

export function getStatus(id: PermissionId): PermissionStatus {
  switch (id) {
    case "microphone":
      return mapMediaStatus(systemPreferences.getMediaAccessStatus("microphone"));
    case "accessibility":
      return systemPreferences.isTrustedAccessibilityClient(false) ? "granted" : "denied";
    case "inputMonitoring":
      return helperLooksAlive() ? "granted" : "denied";
  }
}

export function getAll(): PermissionState[] {
  return [
    {
      id: "microphone",
      status: getStatus("microphone"),
      canAutoRequest: true,
      hint: "Needed to capture your voice while you hold the hotkey.",
    },
    {
      id: "accessibility",
      status: getStatus("accessibility"),
      canAutoRequest: true,
      hint: "Needed to type dictated text into the focused app.",
    },
    {
      id: "inputMonitoring",
      status: getStatus("inputMonitoring"),
      canAutoRequest: false,
      hint: "Needed to detect when you hold the hotkey. macOS requires you to toggle this manually.",
    },
  ];
}

/** Attempt to request a permission. Returns the post-request status. */
export async function request(id: PermissionId): Promise<PermissionStatus> {
  switch (id) {
    case "microphone": {
      await systemPreferences.askForMediaAccess("microphone");
      return getStatus("microphone");
    }
    case "accessibility": {
      // Passing true to isTrustedAccessibilityClient triggers the macOS prompt.
      systemPreferences.isTrustedAccessibilityClient(true);
      return getStatus("accessibility");
    }
    case "inputMonitoring": {
      // Open System Settings on the correct pane and reveal the helper binary
      // in Finder so the user can drag it in.
      await shell.openExternal(
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
      );
      const helperPath = resolveHelperPath();
      if (helperPath && fs.existsSync(helperPath)) {
        shell.showItemInFolder(helperPath);
      }
      return getStatus("inputMonitoring");
    }
  }
}

// ── helpers ────────────────────────────────────────────────────────────────

function mapMediaStatus(s: string): PermissionStatus {
  if (s === "granted") return "granted";
  if (s === "denied" || s === "restricted") return "denied";
  if (s === "not-determined") return "not-determined";
  return "unknown";
}

function resolveHelperPath(): string | null {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "miniflow-fn-helper");
  }
  return path.resolve(
    __dirname, "..", "..", "..", "native-helper", "target", "release", "miniflow-fn-helper"
  );
}

/** We treat the presence of the helper's pidfile plus a live process as a
 *  strong proxy for Input Monitoring being granted. If the helper couldn't
 *  install its CGEventTap, it exits; the pidfile may still exist but the
 *  process is gone. */
function helperLooksAlive(): boolean {
  const pidfile = path.join(process.env.HOME || "", "miniflow", "miniflow-fn-helper.pid");
  try {
    if (!fs.existsSync(pidfile)) return false;
    const pid = parseInt(fs.readFileSync(pidfile, "utf8").trim(), 10);
    if (!pid) return false;
    // kill(pid, 0) throws ESRCH if the process doesn't exist.
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
