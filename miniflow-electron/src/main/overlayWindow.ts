// Floating approval overlay — always-on-top island near the macOS notch.
// Appears when the agent needs confirmation; dismisses after user responds.

import { BrowserWindow, screen } from "electron";
import path from "node:path";

let _overlay: BrowserWindow | null = null;

export function getOverlayWindow(): BrowserWindow | null {
  return _overlay && !_overlay.isDestroyed() ? _overlay : null;
}

export function createOverlayWindow(): BrowserWindow {
  if (_overlay && !_overlay.isDestroyed()) return _overlay;

  const { width } = screen.getPrimaryDisplay().workAreaSize;

  _overlay = new BrowserWindow({
    width: 412,
    height: 420,
    x: Math.round((width - 412) / 2),
    y: 0,
    frame: false,
    transparent: true,
    hasShadow: false,
    alwaysOnTop: true,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    show: false,
    focusable: true,
    webPreferences: {
      preload: path.join(__dirname, "../preload/preload.js"),
      contextIsolation: true,
      sandbox: true,
    },
  });

  // Sit above everything including full-screen apps
  _overlay.setAlwaysOnTop(true, "screen-saver");
  _overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  const isDev = !require("electron").app.isPackaged;
  if (isDev) {
    _overlay.loadURL("http://localhost:5174/overlay.html");
  } else {
    _overlay.loadFile(path.join(__dirname, "../renderer/overlay.html"));
  }

  _overlay.on("closed", () => { _overlay = null; });

  return _overlay;
}

export function showOverlay(): void {
  const w = getOverlayWindow() ?? createOverlayWindow();
  if (!w.isVisible()) w.showInactive();
}

export function hideOverlay(): void {
  getOverlayWindow()?.hide();
}
