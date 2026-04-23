// WebSocket client to the Python backend — streams agent events to the renderer.

import WebSocket from "ws";
import { BrowserWindow } from "electron";
import { EventEmitter } from "events";

import { WS_URL } from "./api";
import { IpcChannels } from "../shared/types";
import { showOverlay, hideOverlay, createOverlayWindow } from "./overlayWindow";

let ws: WebSocket | null = null;
let getWindows: (() => BrowserWindow[]) = () => [];

export function setWindowProvider(fn: () => BrowserWindow[]) {
  getWindows = fn;
}

/** Emits "chunk" events for streamed dictation text so main/index.ts can
 *  pipe them directly to the Rust helper without an extra IPC hop. */
export const chunkBus = new EventEmitter();

export function connectWs(): void {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket(WS_URL);

  ws.on("open", () => console.log("[ws] connected"));
  ws.on("close", () => {
    console.log("[ws] closed, reconnecting in 2s");
    ws = null;
    setTimeout(connectWs, 2000);
  });
  ws.on("error", (err) => console.error("[ws]", err.message));
  ws.on("message", (raw) => {
    let msg: { event: string; payload: unknown };
    try { msg = JSON.parse(raw.toString("utf8")); }
    catch { return; }

    // Fast path: streamed grammar-correction chunks go straight to the helper
    // via an in-process event bus. No IPC round-trip.
    if (msg.event === "action-chunk") {
      const chunk = (msg.payload as { chunk?: string } | null)?.chunk;
      if (chunk) chunkBus.emit("chunk", chunk);
      // Fall through so the renderer can still surface it in the UI preview.
    }

    // Floating overlay: show on approval-needed, hide on resolved/result
    if (msg.event === "approval-needed") showOverlay();
    if (msg.event === "approval-resolved") hideOverlay();

    forwardToRenderer(msg.event, msg.payload);
  });
}

function forwardToRenderer(event: string, payload: unknown): void {
  // Event name → renderer IPC channel. Anything not in this map is dropped.
  const channel: string | null =
    event === "agent-status"        ? IpcChannels.agentStatus :
    event === "action-result"       ? IpcChannels.actionResult :
    event === "action-chunk"        ? "agent:chunk" :
    event === "transcription"       ? "voice:transcription" :
    event === "transcription-error" ? "voice:transcription-error" :
    event === "oauth-connected"     ? "oauth:connected" :
    event === "debug"               ? "debug:event" :
    event === "approval-needed"     ? "agent:approval-needed" :
    event === "approval-resolved"   ? "agent:approval-resolved" :
    null;
  if (!channel) return;
  // Broadcast to every live BrowserWindow exactly ONCE. We used to also loop
  // via getWindows() which double-fired every action, so the helper was
  // typing dictation text twice.
  const seen = new Set<number>();
  for (const w of BrowserWindow.getAllWindows()) {
    if (w.isDestroyed() || seen.has(w.id)) continue;
    seen.add(w.id);
    w.webContents.send(channel, payload);
  }
}
