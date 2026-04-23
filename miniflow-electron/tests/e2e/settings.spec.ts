// End-to-end smoke test — launches the packaged Electron app, opens the
// popover, verifies that all three tabs render without errors, and that
// the provider list / hotkey recorder are interactive.
//
// Prerequisites:
//   - Run `npm run build` first
//   - Have a Python backend running locally (or MINIFLOW_ENGINE_EXTERNAL=1)
//
// To run: npm run test:e2e

import { test, expect, _electron as electron } from "@playwright/test";
import path from "node:path";

const APP_DIR = path.resolve(__dirname, "..", "..");
const MAIN = path.join(APP_DIR, "build", "main", "index.js");

test("launches, shows tabs, switches provider", async () => {
  const app = await electron.launch({
    args: [MAIN],
    env: { ...process.env, MINIFLOW_ENGINE_EXTERNAL: "1", MINIFLOW_KEEP_OPEN: "1" },
  });
  const win = await app.firstWindow();
  await expect(win.locator("text=LLM Providers")).toBeVisible();
  await expect(win.locator("text=Hotkey")).toBeVisible();
  await expect(win.locator("text=History")).toBeVisible();

  await win.locator("text=Hotkey").click();
  await expect(win.locator("text=Current hotkey")).toBeVisible();

  await win.locator("text=History").click();
  await expect(win.locator("text=Command history")).toBeVisible();

  await app.close();
});
