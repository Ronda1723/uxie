// Native macOS notification fired when the engine detects a meeting about
// to start. Action buttons let the user accept ("Record") or skip without
// having to open the popover. On Windows we fall back to a basic toast —
// Notification action buttons aren't reliable cross-platform.

import { Notification, BrowserWindow } from "electron";

import { invoke } from "./api";
import { popoverWindow } from "./tray";

type DetectedPayload = {
  id?: number;
  title?: string;
  start_ts?: number;
  end_ts?: number;
  meeting_url?: string;
  attendees?: Array<{ email?: string; name?: string }>;
};

function formatTimeUntil(startTs: number | undefined): string {
  if (!startTs) return "starting now";
  const delta = startTs - Math.floor(Date.now() / 1000);
  if (delta <= 30) return "starting now";
  if (delta < 90) return `in ${delta}s`;
  return `in ${Math.round(delta / 60)} min`;
}

function shortDomain(url: string): string {
  try {
    const host = new URL(url).host;
    if (host.includes("zoom.us")) return "your Zoom call";
    if (host.includes("meet.google.com")) return "your Meet call";
    if (host.includes("teams.microsoft.com")) return "your Teams call";
    return "the call";
  } catch {
    return "the call";
  }
}

export function showMeetingDetectedNotification(payload: DetectedPayload): void {
  if (!Notification.isSupported() || !payload?.id) return;
  const title = (payload.title || "Meeting").slice(0, 80);
  const when = formatTimeUntil(payload.start_ts);

  const body = payload.meeting_url
    ? `Record this meeting? Uxie will transcribe ${shortDomain(payload.meeting_url)} in the background.`
    : "Record this meeting? Uxie will transcribe in the background.";

  const n = new Notification({
    title: `${title} — ${when}`,
    body,
    actions: process.platform === "darwin"
      ? [
          { type: "button", text: "Record" },
          { type: "button", text: "Skip" },
        ]
      : [],
    silent: false,
  });

  // macOS: clicking an action button delivers an `action` event indexed by
  // position in the actions array. Body click delivers `click`.
  n.on("action", (_e, index) => {
    if (index === 0) startRecording(payload.id!);
    else if (index === 1) skipMeeting(payload.id!);
  });
  n.on("click", () => {
    // Open the popover focused on the Meetings tab; user can still decide
    // there if they didn't click an action button.
    revealMeetingsTab();
  });

  n.show();
}

async function startRecording(meetingId: number): Promise<void> {
  try {
    await invoke("start_meeting_recording", { id: meetingId });
  } catch (e) {
    console.error("[meeting] start_recording failed:", e);
    return;
  }
  // Slice 2 will start the audio tap here. For now, just refresh the UI.
  broadcastMeetingsRefresh();
}

async function skipMeeting(meetingId: number): Promise<void> {
  try {
    await invoke("skip_meeting", { id: meetingId });
  } catch (e) {
    console.error("[meeting] skip failed:", e);
  }
  broadcastMeetingsRefresh();
}

function revealMeetingsTab(): void {
  const w = popoverWindow();
  if (!w || w.isDestroyed()) return;
  if (!w.isVisible()) w.show();
  w.focus();
  w.webContents.send("meetings:reveal", null);
}

function broadcastMeetingsRefresh(): void {
  for (const w of BrowserWindow.getAllWindows()) {
    if (!w.isDestroyed()) w.webContents.send("meetings:refresh", null);
  }
}
