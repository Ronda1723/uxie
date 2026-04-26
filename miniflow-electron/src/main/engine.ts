// Supervises the PyInstaller-bundled Python backend.
//
// In development: expects the user to run `cd ../miniflow-engine && ./venv/bin/python main.py`
// themselves (we just wait for /health). Set MINIFLOW_ENGINE_EXTERNAL=1 to skip spawning.
//
// In production: spawns Resources/miniflow-engine/miniflow-engine from inside the .app.

import { spawn, ChildProcess } from "node:child_process";
import { app } from "electron";
import path from "node:path";
import fs from "node:fs";

import { waitUntilHealthy } from "./api";

let engineProc: ChildProcess | null = null;

function engineBinaryPath(): string {
  // PyInstaller appends .exe on Windows; bare on macOS. Same logic for the
  // packaged Resources path and the dev sibling-dir fallback.
  const exeName = process.platform === "win32" ? "miniflow-engine.exe" : "miniflow-engine";
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "miniflow-engine", exeName);
  }
  // Dev: assume sibling source dir. Users will typically run the Python directly,
  // so we only try to spawn if the PyInstaller output exists.
  return path.resolve(
    __dirname, "..", "..", "..", "miniflow-engine", "dist", "miniflow-engine", exeName
  );
}

export async function startEngine(): Promise<void> {
  if (process.env.MINIFLOW_ENGINE_EXTERNAL === "1") {
    console.log("[engine] MINIFLOW_ENGINE_EXTERNAL=1 — waiting for existing backend");
    await waitUntilHealthy();
    return;
  }

  const bin = engineBinaryPath();
  if (!fs.existsSync(bin)) {
    console.warn(
      `[engine] binary not found at ${bin}. ` +
      "Run build_backend.sh or set MINIFLOW_ENGINE_EXTERNAL=1."
    );
    // Best-effort: wait in case the user started it manually
    await waitUntilHealthy(5000).catch(() => {
      throw new Error(
        "Python backend is not running and no bundled binary was found."
      );
    });
    return;
  }

  console.log(`[engine] spawning ${bin}`);
  engineProc = spawn(bin, [], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env },
  });
  engineProc.stdout?.on("data", (d) => process.stdout.write(`[engine] ${d}`));
  engineProc.stderr?.on("data", (d) => process.stderr.write(`[engine-err] ${d}`));
  engineProc.on("exit", (code, sig) =>
    console.log(`[engine] exited code=${code} signal=${sig}`)
  );

  await waitUntilHealthy();
  console.log("[engine] healthy");
}

export function stopEngine(): void {
  if (engineProc && !engineProc.killed) {
    engineProc.kill("SIGTERM");
    engineProc = null;
  }
}
