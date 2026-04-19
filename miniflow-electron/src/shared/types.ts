// Types shared between main, preload, and renderer.

export type HotkeyMode = "hold_to_talk" | "press_to_toggle";
export type HotkeyModifier =
  | "fn" | "cmd" | "option" | "control" | "shift" | "globe";

export interface Hotkey {
  mode: HotkeyMode;
  modifier: HotkeyModifier | null;
  key: string | null; // null for modifier-only (default Fn)
}

export interface LLMProvider {
  id: string;
  display_name: string;
  requires_key: boolean;
  supports_tools: boolean;
  default_model: string;
  suggested_models: string[];
}

export interface LLMProviderStatus {
  configured: boolean;
  model: string;
  base_url: string | null;
  is_active: boolean;
}

export type LLMStatus = Record<string, LLMProviderStatus>;

export interface AgentAction {
  action: string;
  success: boolean;
  message: string;
}

export type HelperEvent =
  | { press: true }
  | { release: true }
  | { toggle: true; on: boolean }
  | { error: true; message: string };

// Channels exposed via contextBridge. Keep in sync with preload.ts.
export const IpcChannels = {
  // Provider / settings
  listProviders: "llm:list",
  getStatus: "llm:status",
  setActive: "llm:setActive",
  setModel: "llm:setModel",
  setApiKey: "llm:setKey",
  clearApiKey: "llm:clearKey",
  // Hotkey
  getHotkey: "hotkey:get",
  setHotkey: "hotkey:set",
  resetHotkey: "hotkey:reset",
  // Voice capture lifecycle (main → renderer)
  startCapture: "voice:start",
  stopCapture: "voice:stop",
  // Audio chunk upload (renderer → main)
  audioChunk: "voice:chunk",
  // Agent events (main → renderer)
  actionResult: "agent:action",
  agentStatus: "agent:status",
  // History
  getHistory: "history:get",
  clearHistory: "history:clear",
  // App
  openExternal: "app:openExternal",
  quit: "app:quit",
} as const;

export type IpcChannel = typeof IpcChannels[keyof typeof IpcChannels];
