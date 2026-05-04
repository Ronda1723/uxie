// Floating Uxie widget — bottom-center always-on-top capsule. Houses every
// widget state from docs/widgets.md (dictating, transcribing, thinking,
// acting, done, error, review, countdown, hint, dict, snip).
//
// Geometry: anchored to bottom-center of the primary display, 16 px above
// the dock. Width is fixed; height grows/shrinks as content changes (the
// `dictating` capsule is short, the `review*` cards are tall). Renderer
// asks the main process to resize via `widget:resize` IPC when it knows
// the natural height of the current state.

import { BrowserWindow, ipcMain, screen } from "electron";
import path from "node:path";

const WIDGET_WIDTH = 480;
const DEFAULT_HEIGHT = 80;
const DOCK_GAP = 16;

let _overlay: BrowserWindow | null = null;

export function getOverlayWindow(): BrowserWindow | null {
  return _overlay && !_overlay.isDestroyed() ? _overlay : null;
}

export function createOverlayWindow(): BrowserWindow {
  if (_overlay && !_overlay.isDestroyed()) return _overlay;

  const bounds = computeBounds(DEFAULT_HEIGHT);

  _overlay = new BrowserWindow({
    ...bounds,
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

  // Float above everything including full-screen apps and Spaces switches.
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

/** Resize without moving the bottom anchor. Called by main when the
 *  renderer reports a new natural height for the current state. */
export function resizeOverlay(height: number): void {
  const w = getOverlayWindow();
  if (!w) return;
  const clamped = Math.max(56, Math.min(560, Math.round(height)));
  w.setBounds(computeBounds(clamped), true);
}

function computeBounds(height: number): { x: number; y: number; width: number; height: number } {
  const display = screen.getPrimaryDisplay();
  const wa = display.workArea; // excludes dock + menu bar
  const x = wa.x + Math.round((wa.width - WIDGET_WIDTH) / 2);
  // Anchor to BOTTOM of the work area, with a small gap above the dock.
  const y = wa.y + wa.height - height - DOCK_GAP;
  return { x, y, width: WIDGET_WIDTH, height };
}

// IPC: renderer reports natural height after each state morph.
ipcMain.on("widget:resize", (_e, height: number) => {
  if (typeof height === "number" && Number.isFinite(height)) resizeOverlay(height);
});
