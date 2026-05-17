// Menu-bar tray and popover window.
// On macOS, LSUIElement=true in Info.plist gives us a proper menu-bar-only app.

import { app, Menu, Tray, BrowserWindow, nativeImage, screen } from "electron";
import path from "node:path";

let tray: Tray | null = null;
let popover: BrowserWindow | null = null;
let popoverPinned = false;

export function setPopoverPinned(v: boolean): void { popoverPinned = v; }

const RENDERER_DEV_URL = "http://localhost:5174";

export function createTray(): Tray {
  // Template image for the menu bar — adapts to light/dark appearance.
  // Packaged: <app>/Contents/Resources/iconTemplate.png  (via extraResources)
  // Dev:      miniflow-electron/resources/iconTemplate.png
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "iconTemplate.png")
    : path.resolve(__dirname, "..", "..", "resources", "iconTemplate.png");
  const img = nativeImage.createFromPath(iconPath);
  img.setTemplateImage(true);
  if (img.isEmpty()) {
    console.warn(`[tray] icon not found at ${iconPath}; using fallback`);
  }
  tray = new Tray(img);
  tray.setToolTip("Uxie");

  tray.on("click", togglePopover);
  tray.on("right-click", () => {
    const ctx = Menu.buildFromTemplate([
      { label: "Open Settings", click: togglePopover },
      { type: "separator" },
      { label: "Quit Uxie", click: () => app.quit() },
    ]);
    tray?.popUpContextMenu(ctx);
  });
  return tray;
}

export function togglePopover(): void {
  if (!popover) {
    popover = createPopover();
  }
  if (popover.isVisible()) {
    popover.hide();
    return;
  }
  positionPopoverBelowTray();
  popover.show();
  popover.focus();
}

function createPopover(): BrowserWindow {
  const win = new BrowserWindow({
    width: 860,
    height: 600,
    show: false,
    frame: false,              // custom frame to match Swift's traffic-light-only chrome
    titleBarStyle: "hidden",
    resizable: false,
    hasShadow: true,
    transparent: false,
    backgroundColor: "#F3F3F1",
    vibrancy: undefined,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  const indexPath = path.join(__dirname, "..", "renderer", "index.html");
  console.log(`[tray] loading renderer from: ${indexPath}`);
  if (app.isPackaged) {
    win.loadFile(indexPath).catch((e) => console.error("[tray] loadFile failed:", e));
  } else {
    win.loadURL(RENDERER_DEV_URL);
  }
  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    console.error(`[tray] did-fail-load code=${code} desc=${desc} url=${url}`);
  });
  win.webContents.on("render-process-gone", (_e, details) => {
    console.error(`[tray] render-process-gone:`, details);
  });
  // DevTools: off by default. Enable with MINIFLOW_DEVTOOLS=1 or Cmd+Alt+I.
  if (process.env.MINIFLOW_DEVTOOLS === "1") {
    win.webContents.openDevTools({ mode: "detach" });
  }
  win.webContents.on("before-input-event", (_e, input) => {
    if (input.meta && input.alt && input.key.toLowerCase() === "i") {
      win.webContents.toggleDevTools();
    }
  });
  // No auto-hide on blur — Uxie is now a regular Dock app, the window
  // stays open until the user minimises or closes it. Closing the
  // window keeps the app running (see window-all-closed in index.ts);
  // clicking the Dock icon re-opens it via app.on("activate").
  return win;
}

function positionPopoverBelowTray(): void {
  if (!tray || !popover) return;
  // Center the 860×600 window on the primary display instead of anchoring
  // it under the tray — the Swift app used a real window too, not a popover.
  const bounds = tray.getBounds();
  const display = screen.getDisplayMatching(bounds);
  const winBounds = popover.getBounds();
  const x = Math.round(display.workArea.x + (display.workArea.width - winBounds.width) / 2);
  const y = Math.round(display.workArea.y + 60);
  popover.setPosition(x, y, false);
}

export function popoverWindow(): BrowserWindow | null {
  return popover;
}

export function destroyTray(): void {
  tray?.destroy();
  tray = null;
  popover?.close();
  popover = null;
}
