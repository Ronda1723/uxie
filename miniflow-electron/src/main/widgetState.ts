// Widget mode derivation. Subscribes to the firehose of agent / voice
// events from the Python backend, decides which docs/widgets.md state we
// should be in, and broadcasts a single `widget:state` IPC message to the
// overlay renderer. Anything not in this file should NOT call show/hide
// directly — let the state machine here own the overlay's visibility.

import { BrowserWindow } from "electron";
import { showOverlay, hideOverlay } from "./overlayWindow";

export type WidgetMode =
  | { kind: "hidden" }
  | { kind: "dictating"; partial?: string; startedAt: number }
  | { kind: "transcribing"; text: string }
  | { kind: "thinking"; cleaned?: string; routingTo?: string }
  | { kind: "acting"; app?: string; action?: string }
  | { kind: "done"; summary: string }
  | { kind: "error"; message: string }
  | {
      kind: "review";
      tool: string;
      summary: string;
      params: Record<string, unknown>;
    };

let current: WidgetMode = { kind: "hidden" };
let doneTimer: ReturnType<typeof setTimeout> | null = null;
let safetyTimer: ReturnType<typeof setTimeout> | null = null;

// Last activity time across all modes — used so any new event resets the
// "stuck capsule" safety timer.
function armSafetyTimer(ms: number) {
  if (safetyTimer) clearTimeout(safetyTimer);
  safetyTimer = setTimeout(() => {
    // If we're still in a "transient" state with no fresh activity, hide.
    if (current.kind === "acting" || current.kind === "thinking" || current.kind === "transcribing") {
      console.log("[widget] safety timer fired — clearing stuck state", current.kind);
      setMode({ kind: "hidden" });
    }
  }, ms);
}

export function setMode(next: WidgetMode): void {
  if (doneTimer) { clearTimeout(doneTimer); doneTimer = null; }
  current = next;

  if (next.kind === "hidden") {
    hideOverlay();
    if (safetyTimer) { clearTimeout(safetyTimer); safetyTimer = null; }
  } else {
    showOverlay();
  }

  broadcast(next);

  // `done` auto-dismisses after 1.6s per spec.
  if (next.kind === "done") {
    doneTimer = setTimeout(() => {
      // Only auto-hide if we're still showing the same `done` state — a new
      // press could have moved us elsewhere by now.
      if (current.kind === "done") setMode({ kind: "hidden" });
    }, 1600);
  }

  // Transient states get a 30 s safety net. Any incoming event resets it.
  // This prevents the capsule from sitting forever if the Python engine
  // never emits a terminal event (action-result / final-text / done).
  if (next.kind === "acting" || next.kind === "thinking" || next.kind === "transcribing") {
    armSafetyTimer(30_000);
  }
}

export function getMode(): WidgetMode { return current; }

function broadcast(mode: WidgetMode): void {
  for (const w of BrowserWindow.getAllWindows()) {
    if (w.isDestroyed()) continue;
    w.webContents.send("widget:state", mode);
  }
}

// ── Event mappers — translate raw backend events into widget moves ──────────
//
// Some of these triggers don't exist in the WS stream today (e.g. an explicit
// "voice-start" when fn is pressed). The right place to add them is the
// Python side; until they arrive we infer from what we have.

/** Called when push-to-talk starts (fn-press). main/index.ts wires this to
 *  the helper's keydown so the widget shows the moment the user begins. */
export function onVoiceStart(): void {
  setMode({ kind: "dictating", startedAt: Date.now() });
}

/** Called on fn-release. STT may still be cleaning up. Show transcribing
 *  even if the partial text is empty so the user gets a continuity cue. */
export function onVoiceEnd(partial: string): void {
  setMode({ kind: "transcribing", text: partial });
}

/** Interim STT chunk arrived. Update the dictating partial OR transcribing
 *  text in place — both states have the same payload shape conceptually. */
export function onTranscriptionInterim(text: string): void {
  if (current.kind === "dictating") {
    setMode({ kind: "dictating", partial: text, startedAt: current.startedAt });
  } else if (current.kind === "transcribing") {
    setMode({ kind: "transcribing", text });
  }
}

/** Final transcript. Move to thinking — the LLM is now routing. */
export function onTranscriptionFinal(text: string): void {
  if (!text || !text.trim()) {
    // Empty utterance — no command to run. Hide.
    setMode({ kind: "hidden" });
    return;
  }
  setMode({ kind: "thinking", cleaned: text });
}

/** Generic agent-status events from Python. Strings vary; treat them as
 *  transient acting labels until a result lands.
 *
 *  Empty / "idle" / "done" statuses are treated as terminal — they mean
 *  the engine has nothing more to report, so we hide rather than sit on
 *  a stuck "Running" capsule forever. */
export function onAgentStatus(status: string): void {
  if (current.kind === "review") return; // don't clobber the review card
  const s = (status || "").trim().toLowerCase();
  if (!s || s === "idle" || s === "done" || s === "completed" || s === "ready") {
    setMode({ kind: "hidden" });
    return;
  }
  setMode({ kind: "acting", action: status });
}

/** Streamed dictation/grammar-correction chunk. Each chunk means progress;
 *  treat it as a heartbeat that resets the safety timer. Dictation text is
 *  being typed into the user's focused app, so we don't render anything
 *  visible — just stay in the current state and let the next state event
 *  (typically agent-status="idle" or action-result) close the widget. */
export function onActionChunk(_chunk: string): void {
  if (current.kind === "acting" || current.kind === "thinking" || current.kind === "transcribing") {
    // Re-arm the 30 s safety net; chunks indicate the agent is alive.
    setMode(current);
  }
}

/** Action result — success or failure. */
export function onActionResult(payload: { ok?: boolean; summary?: string; error?: string }): void {
  if (payload.ok === false || payload.error) {
    setMode({ kind: "error", message: payload.error || payload.summary || "Action failed" });
  } else {
    setMode({ kind: "done", summary: payload.summary || "Done" });
  }
}

/** Approval request — the spec's review state. */
export function onApprovalNeeded(payload: { tool: string; summary: string; params: Record<string, unknown> }): void {
  setMode({ kind: "review", tool: payload.tool, summary: payload.summary, params: payload.params || {} });
}

export function onApprovalResolved(): void {
  // Fall back to the prior `acting` cue while the action runs. The result
  // event will land us in `done` or `error`.
  setMode({ kind: "acting" });
}

/** Force the widget away — used by Esc handling and explicit cancel. */
export function dismiss(): void { setMode({ kind: "hidden" }); }
