// Global typing for window.miniflow (populated by the preload script).

import type {
  Hotkey, LLMProvider, LLMStatus, AgentAction,
} from "@shared/types";

interface MiniflowAPI {
  // LLM
  listProviders():   Promise<LLMProvider[]>;
  getLLMStatus():    Promise<LLMStatus>;
  setActiveLLM(id: string): Promise<unknown>;
  setLLMModel(id: string, model: string, baseUrl: string | null): Promise<unknown>;
  setLLMKey(id: string, key: string): Promise<unknown>;
  clearLLMKey(id: string): Promise<unknown>;
  // Hotkey
  getHotkey(): Promise<Hotkey>;
  setHotkey(h: Hotkey): Promise<Hotkey>;
  resetHotkey(): Promise<Hotkey>;
  // Voice
  sendAudioChunk(base64: string): Promise<unknown>;
  onStartCapture(cb: () => void): () => void;
  onStopCapture(cb: () => void): () => void;
  onAction(cb: (a: AgentAction) => void): () => void;
  onAgentStatus(cb: (s: string) => void): () => void;
  // History
  getHistory(): Promise<unknown>;
  clearHistory(): Promise<unknown>;
  // App
  openExternal(url: string): Promise<unknown>;
  quit(): Promise<unknown>;
  // Helper
  requestType(text: string): void;
}

declare global {
  interface Window {
    miniflow: MiniflowAPI;
  }
}

export {};
