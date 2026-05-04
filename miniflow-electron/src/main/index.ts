// Electron main process entry point.

import * as electronNS from "electron";
import { powerMonitor } from "electron";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Early crash logger — writes to ~/miniflow/electron-main.log so we can diagnose
// silent crashes on packaged runs where stderr is discarded.
const _logPath = path.join(os.homedir(), "miniflow", "electron-main.log");
try { fs.mkdirSync(path.dirname(_logPath), { recursive: true }); } catch {}
function _log(msg: string) {
  try { fs.appendFileSync(_logPath, `[${new Date().toISOString()}] ${msg}\n`); } catch {}
  console.log(msg);
}
_log(`boot pid=${process.pid} argv=${process.argv.join(" ")}`);
_log(`process.type=${(process as any).type} versions=${JSON.stringify(process.versions)}`);
_log(`electron typeof: ${typeof electronNS}; ctor: ${electronNS?.constructor?.name}; props: ${Object.getOwnPropertyNames(electronNS as any).slice(0, 20).join(",")}`);
_log(`electron.app typeof: ${typeof (electronNS as any).app}`);
process.on("uncaughtException", (e) => _log(`UNCAUGHT: ${e?.stack || e}`));
process.on("unhandledRejection", (e: any) => _log(`UNHANDLED: ${e?.stack || e}`));

// Electron exposes the public API as the module's default export on CommonJS
// builds. Some tooling flattens it onto the namespace; support both.
const { app, BrowserWindow } = ((electronNS as any).app
  ? (electronNS as any)
  : (electronNS as any).default) as typeof import("electron");

import { startEngine, stopEngine } from "./engine";
import { helper } from "./helper";
import { createTray, destroyTray, popoverWindow } from "./tray";
import { connectWs, setWindowProvider } from "./websocket";
import { registerIpc } from "./ipc";
import { invoke } from "./api";
import { IpcChannels } from "../shared/types";
import { createOverlayWindow } from "./overlayWindow";
import { onVoiceStart, onVoiceEnd } from "./widgetState";
import { getFrontmostAppId, hideDockIcon } from "./platform";
import { autoUpdater } from "electron-updater";

// Hide from dock on macOS (no-op on Windows). LSUIElement in Info.plist
// also enforces this on macOS.
hideDockIcon(app);

// Single instance lock
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

app.whenReady().then(async () => {
  try {
    await startEngine();
  } catch (e) {
    console.error("Engine failed to start:", e);
  }

  // Auto-update: Windows-only for now. The macOS auto-update path needs a
  // signed/notarized DMG (Apple Developer cert), which we don't have yet —
  // calling autoUpdater there would just log noisy signature errors. Wire
  // Mac in later when the cert lands. Skipped in dev (app.isPackaged false).
  if (app.isPackaged && process.platform === "win32") {
    autoUpdater.logger = {
      info:  (m: any) => _log(`[updater] info: ${m}`),
      warn:  (m: any) => _log(`[updater] warn: ${m}`),
      error: (m: any) => _log(`[updater] error: ${m?.stack ?? m}`),
      debug: (_m: any) => {},
    } as any;
    autoUpdater.checkForUpdatesAndNotify().catch((e) =>
      _log(`[updater] checkForUpdatesAndNotify failed: ${e?.stack ?? e}`)
    );
  }

  createTray();
  setWindowProvider(() => {
    const w = popoverWindow();
    return w ? [w] : [];
  });

  // Pre-create the overlay window so it's ready to slide in instantly
  createOverlayWindow();

  connectWs();
  registerIpc();

  // Wire the Rust helper to the renderer. Each event carries a mode
  // ("dictation" or "command") which the backend uses to branch on stop.
  helper.on("press", (mode) => onPress(mode));
  helper.on("release", (mode) => onRelease(mode));
  helper.on("toggle", (mode, on) => (on ? onPress(mode) : onRelease(mode)));
  helper.on("error", (m) => console.error("[helper]", m));
  helper.start();

  // Broadcast start/stop to the popover window; the renderer owns the mic.
  function onPress(mode: "dictation" | "command") {
    // Capture bundle ID FIRST — before broadcast which may steal focus.
    // On Windows this currently returns null until we wire UIAutomation;
    // the agent treats null as "no target app context" and dictation still
    // works fine.
    const bundleID = getFrontmostAppId();
    console.log("[hotkey] bundleID:", bundleID);
    broadcast(IpcChannels.startCapture, { mode });
    // Bring the floating widget up the moment the user begins holding fn,
    // before any audio has been captured. Latency here = perceived snappiness.
    onVoiceStart();
    invoke("start_listening", { sampleRate: 16000, mode, bundleID }).catch((e) =>
      console.error("start_listening failed:", e)
    );
  }
  function onRelease(mode: "dictation" | "command") {
    broadcast(IpcChannels.stopCapture, { mode });
    onVoiceEnd("");
    invoke("stop_listening").catch((e) =>
      console.error("stop_listening failed:", e)
    );
  }

  // Force-stop the mic when macOS is about to sleep/lock. The native hotkey
  // event-tap can lose `fn` release events across power transitions, which
  // leaves the renderer holding the microphone forever. Releasing defensively
  // on suspend + resume + lock means the orange indicator turns off no matter
  // what the keyboard hook did.
  const forceStop = (reason: string) => {
    _log(`power event: ${reason} — force stop mic`);
    broadcast(IpcChannels.stopCapture, { mode: "dictation" });
    invoke("stop_listening").catch(() => {});
  };
  powerMonitor.on("suspend",      () => forceStop("suspend"));
  powerMonitor.on("resume",       () => forceStop("resume"));
  powerMonitor.on("lock-screen",  () => forceStop("lock-screen"));
  powerMonitor.on("shutdown",     () => forceStop("shutdown"));
});

// Renderer → helper bridge for manual type requests (command-bar execute, etc).
import { ipcMain } from "electron";
import { chunkBus } from "./websocket";

ipcMain.on("helper:type", (_e, text: string) => helper.type(text));

// Streaming dictation: each LLM token chunk goes straight from WebSocket →
// chunkBus → helper. No renderer IPC hop, no React re-render latency.
chunkBus.on("chunk", (s: string) => helper.type(s));

function broadcast(channel: string, payload: unknown) {
  // Send to every window exactly once.
  const seen = new Set<number>();
  for (const w of BrowserWindow.getAllWindows()) {
    if (w.isDestroyed() || seen.has(w.id)) continue;
    seen.add(w.id);
    w.webContents.send(channel, payload);
  }
}

app.on("window-all-closed", () => {
  // Intentionally do nothing — we live in the menu bar and should keep running
  // even if the popover window is closed.
});

app.on("before-quit", () => {
  helper.quit();
  stopEngine();
  destroyTray();
});
