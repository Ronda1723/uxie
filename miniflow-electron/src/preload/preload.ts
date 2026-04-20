// Preload runs with sandbox: true, so require() is restricted to Electron's
// built-in modules. We cannot import from ../shared/types — inline the channel
// names here instead. Keep these strings in sync with src/shared/types.ts.

import { contextBridge, ipcRenderer, IpcRendererEvent } from "electron";

const CH = {
  listProviders: "llm:list",
  getStatus: "llm:status",
  setActive: "llm:setActive",
  setModel: "llm:setModel",
  setApiKey: "llm:setKey",
  clearApiKey: "llm:clearKey",
  revealKeysFile: "llm:revealFile",
  saveSmallestKey: "stt:setKey",
  getHotkey: "hotkey:get",
  setHotkey: "hotkey:set",
  resetHotkey: "hotkey:reset",
  startCapture: "voice:start",
  stopCapture: "voice:stop",
  audioChunk: "voice:chunk",
  transcription: "voice:transcription",
  transcriptionError: "voice:transcription-error",
  actionResult: "agent:action",
  agentStatus: "agent:status",
  getHistory: "history:get",
  clearHistory: "history:clear",
  executeCommand: "agent:execute",
  permGetAll: "perm:getAll",
  permRequest: "perm:request",
  windowPin: "window:pin",
  openExternal: "app:openExternal",
  quit: "app:quit",
  // Auth
  sendOtp: "auth:sendOtp",
  verifyOtp: "auth:verifyOtp",
  getUserStatus: "auth:userStatus",
  getUxieUser: "auth:uxieUser",
  logout: "auth:logout",
} as const;

function listen<T>(channel: string, cb: (value: T) => void) {
  const handler = (_e: IpcRendererEvent, value: T) => cb(value);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

const api = {
  // LLM
  listProviders:  () => ipcRenderer.invoke(CH.listProviders),
  getLLMStatus:   () => ipcRenderer.invoke(CH.getStatus),
  setActiveLLM:   (id: string) => ipcRenderer.invoke(CH.setActive, id),
  setLLMModel:    (id: string, model: string, baseUrl: string | null) =>
    ipcRenderer.invoke(CH.setModel, id, model, baseUrl),
  setLLMKey:      (id: string, key: string) => ipcRenderer.invoke(CH.setApiKey, id, key),
  clearLLMKey:    (id: string) => ipcRenderer.invoke(CH.clearApiKey, id),
  revealKeysFile: () => ipcRenderer.invoke(CH.revealKeysFile),
  revealLog:        () => ipcRenderer.invoke("fs:revealLog"),
  openMiniflowDir:  () => ipcRenderer.invoke("fs:openMiniflowDir"),

  // Smallest AI (STT)
  saveSmallestKey: (k: string) => ipcRenderer.invoke(CH.saveSmallestKey, k),

  // Transcription events
  onTranscription: (cb: (p: { transcript: string; is_final: boolean; is_session?: boolean }) => void) =>
    listen(CH.transcription, cb),
  onTranscriptionError: (cb: (err: string) => void) =>
    listen<string>(CH.transcriptionError, cb),

  // Execute a typed-in text command through the agent
  executeCommand: (text: string) => ipcRenderer.invoke(CH.executeCommand, text),

  // Permissions
  getPermissions:     () => ipcRenderer.invoke(CH.permGetAll),
  requestPermission:  (id: "microphone" | "accessibility" | "inputMonitoring") =>
    ipcRenderer.invoke(CH.permRequest, id),
  pinWindow:          (pinned: boolean) => ipcRenderer.invoke(CH.windowPin, pinned),

  // Hotkey
  getHotkey:      () => ipcRenderer.invoke(CH.getHotkey),
  setHotkey:      (h: unknown) => ipcRenderer.invoke(CH.setHotkey, h),
  resetHotkey:    () => ipcRenderer.invoke(CH.resetHotkey),

  // Voice
  sendAudioChunk: (base64: string) => ipcRenderer.invoke(CH.audioChunk, base64),
  onStartCapture: (cb: (p: { mode: "dictation" | "command" }) => void) =>
    listen<{ mode: "dictation" | "command" }>(CH.startCapture, (p) => cb(p ?? { mode: "dictation" })),
  onStopCapture:  (cb: (p: { mode: "dictation" | "command" }) => void) =>
    listen<{ mode: "dictation" | "command" }>(CH.stopCapture, (p) => cb(p ?? { mode: "dictation" })),
  onAction:       (cb: (a: any) => void) => listen<any>(CH.actionResult, cb),
  onAgentStatus:  (cb: (s: string) => void) => listen<string>(CH.agentStatus, cb),
  onDictationChunk: (cb: (chunk: string) => void) =>
    listen<{ chunk?: string }>("agent:chunk", (p) => cb(p?.chunk ?? "")),
  onDebugEvent: (cb: (e: { type: string; text: string; app: string; success?: boolean }) => void) =>
    listen("debug:event", cb),

  // History
  getHistory:     () => ipcRenderer.invoke(CH.getHistory),
  clearHistory:   () => ipcRenderer.invoke(CH.clearHistory),

  // Auth (Uxie backend)
  sendOtp:        (email: string, referralCode?: string) =>
    ipcRenderer.invoke(CH.sendOtp, email, referralCode),
  verifyOtp:      (email: string, code: string) =>
    ipcRenderer.invoke(CH.verifyOtp, email, code),
  getUserStatus:  () => ipcRenderer.invoke(CH.getUserStatus),
  getUxieUser:    () => ipcRenderer.invoke(CH.getUxieUser),
  logout:         () => ipcRenderer.invoke(CH.logout),

  // App
  openExternal:   (url: string) => ipcRenderer.invoke(CH.openExternal, url),
  quit:           () => ipcRenderer.invoke(CH.quit),

  // Helper
  requestType:    (text: string) => ipcRenderer.send("helper:type", text),

  // Dictionary (word → replacement)
  getDictionary:      () => ipcRenderer.invoke("dict:get"),
  addDictWord:        (from: string, to: string) => ipcRenderer.invoke("dict:add", from, to),
  removeDictWord:     (from: string) => ipcRenderer.invoke("dict:remove", from),

  // Snippets (trigger → expansion)
  getSnippets:        () => ipcRenderer.invoke("snip:get"),
  addSnippet:         (trigger: string, expansion: string) => ipcRenderer.invoke("snip:add", trigger, expansion),
  removeSnippet:      (trigger: string) => ipcRenderer.invoke("snip:remove", trigger),
};

contextBridge.exposeInMainWorld("miniflow", api);
