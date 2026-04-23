import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: 0,
  use: {
    // We launch Electron directly from the test — no webServer needed.
    headless: false,
  },
  reporter: [["list"]],
});
