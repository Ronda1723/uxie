// Wire IPC handlers that the preload script exposes to the renderer.

import { ipcMain, shell, app } from "electron";

import { invoke } from "./api";
import { helper } from "./helper";
import { IpcChannels } from "../shared/types";
import type { Hotkey } from "../shared/types";

import * as permissions from "./permissions";
import { setPopoverPinned } from "./tray";

// Extra channels not yet in the shared/types constants (kept in sync with preload.ts)
const EXTRA = {
  revealKeysFile: "llm:revealFile",
  saveSmallestKey: "stt:setKey",
  executeCommand: "agent:execute",
  permGetAll: "perm:getAll",
  permRequest: "perm:request",
  windowPin: "window:pin",
  // Auth
  sendOtp: "auth:sendOtp",
  verifyOtp: "auth:verifyOtp",
  getUserStatus: "auth:userStatus",
  getUxieUser: "auth:uxieUser",
  logout: "auth:logout",
};

export function registerIpc() {
  // Provider / LLM
  ipcMain.handle(IpcChannels.listProviders, () => invoke("list_llm_providers"));
  ipcMain.handle(IpcChannels.getStatus,     () => invoke("get_llm_status"));
  ipcMain.handle(IpcChannels.setActive, (_e, provider: string) =>
    invoke("set_active_llm", { provider })
  );
  ipcMain.handle(IpcChannels.setModel, (_e, provider: string, model: string, base_url: string | null) =>
    invoke("set_llm_model", { provider, model, base_url })
  );
  ipcMain.handle(IpcChannels.setApiKey, (_e, provider: string, api_key: string) =>
    invoke("set_llm_api_key", { provider, api_key })
  );
  ipcMain.handle(IpcChannels.clearApiKey, (_e, provider: string) =>
    invoke("clear_llm_api_key", { provider })
  );

  // Hotkey
  ipcMain.handle(IpcChannels.getHotkey, () => invoke("get_hotkey"));
  ipcMain.handle(IpcChannels.setHotkey, async (_e, hk: Hotkey) => {
    const result = await invoke("set_hotkey", hk as unknown as Record<string, unknown>);
    helper.reload(); // tell the Rust helper to re-read hotkey.json
    return result;
  });
  ipcMain.handle(IpcChannels.resetHotkey, async () => {
    const r = await invoke("reset_hotkey");
    helper.reload();
    return r;
  });

  // Audio chunk from renderer → backend
  ipcMain.handle(IpcChannels.audioChunk, (_e, chunkB64: string) =>
    invoke("send_audio_chunk", { chunk: chunkB64 })
  );

  // History
  ipcMain.handle(IpcChannels.getHistory, () => invoke("get_history"));
  ipcMain.handle(IpcChannels.clearHistory, () => invoke("clear_history"));

  // App
  ipcMain.handle(IpcChannels.openExternal, (_e, url: string) => shell.openExternal(url));
  ipcMain.handle(IpcChannels.quit, () => app.quit());

  // Reveal the plain LLM-keys file in Finder
  ipcMain.handle(EXTRA.revealKeysFile, async () => {
    const { path } = (await invoke("get_llm_keys_file", {})) as { path: string };
    shell.showItemInFolder(path);
    return path;
  });

  // Reveal arbitrary locations under ~/miniflow/ in Finder
  ipcMain.handle("fs:revealLog", async () => {
    const { homedir } = await import("node:os");
    const path = `${homedir()}/miniflow/miniflow.log`;
    shell.showItemInFolder(path);
    return path;
  });
  ipcMain.handle("fs:openMiniflowDir", async () => {
    const { homedir } = await import("node:os");
    shell.openPath(`${homedir()}/miniflow`);
  });

  // Save the Smallest AI (STT) key
  ipcMain.handle(EXTRA.saveSmallestKey, (_e, key: string) =>
    invoke("save_api_key", { service: "smallest", key })
  );

  // Run a typed-in text command through the agent
  ipcMain.handle(EXTRA.executeCommand, (_e, text: string) =>
    invoke("execute_command", { command: text })
  );

  // Approval widget — user clicks "Do it" or "Cancel" (from overlay or in-app)
  ipcMain.handle("agent:resolve-approval", async (_e, approved: boolean) => {
    const { hideOverlay } = await import("./overlayWindow");
    hideOverlay();
    return invoke("resolve_approval", { approved });
  });

  // Permissions — onboarding modal reads + requests these
  ipcMain.handle(EXTRA.permGetAll, () => permissions.getAll());
  ipcMain.handle(EXTRA.permRequest, (_e, id: permissions.PermissionId) =>
    permissions.request(id)
  );

  // Pin the popover open (prevents hide-on-blur during onboarding / sensitive flows)
  ipcMain.handle(EXTRA.windowPin, (_e, pinned: boolean) => setPopoverPinned(!!pinned));

  // MCP connector management
  ipcMain.handle("mcp:getStatus",       () => invoke("mcp_get_status", {}));
  ipcMain.handle("mcp:connectServer",   (_e, serverId: string, credentials: Record<string, string>) =>
    invoke("mcp_connect_server", { server_id: serverId, credentials }));
  ipcMain.handle("mcp:disconnectServer", (_e, serverId: string) =>
    invoke("mcp_disconnect_server", { server_id: serverId }));

  // OAuth connectors (Google, Slack)
  ipcMain.handle("oauth:getConnected", () => invoke("get_connected_providers", {}));
  ipcMain.handle("oauth:start", async (_e, provider: string) => {
    const url = await invoke("start_oauth", { provider }) as string;
    if (url) shell.openExternal(url);
    return url;
  });
  ipcMain.handle("oauth:disconnect", (_e, provider: string) =>
    invoke("disconnect_provider", { provider }));

  // Dictionary
  ipcMain.handle("dict:get",    () => invoke("get_dictionary"));
  ipcMain.handle("dict:add",    (_e, from: string, to: string) => invoke("add_dictionary_word", { from, to }));
  ipcMain.handle("dict:remove", (_e, from: string) => invoke("remove_dictionary_word", { from }));

  // Snippets
  ipcMain.handle("snip:get",    () => invoke("get_snippets"));
  ipcMain.handle("snip:add",    (_e, trigger: string, expansion: string) => invoke("add_snippet", { trigger, expansion }));
  ipcMain.handle("snip:remove", (_e, trigger: string) => invoke("remove_snippet", { trigger }));

  // Auth (Uxie backend)
  ipcMain.handle(EXTRA.sendOtp, (_e, email: string, referralCode?: string) =>
    invoke("send_otp", { email, referral_code: referralCode ?? null })
  );
  ipcMain.handle(EXTRA.verifyOtp, (_e, email: string, code: string) =>
    invoke("verify_otp", { email, code })
  );
  ipcMain.handle(EXTRA.getUserStatus, () => invoke("get_user_status", {}));
  ipcMain.handle(EXTRA.getUxieUser,   () => invoke("get_uxie_user", {}));
  ipcMain.handle(EXTRA.logout,        () => invoke("logout_uxie", {}));
}
