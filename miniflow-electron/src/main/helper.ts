// Supervises the Rust native helper: reads hotkey events from stdout,
// writes typing commands to stdin, sends SIGHUP on config change.

import { spawn, ChildProcess } from "node:child_process";
import { app } from "electron";
import path from "node:path";
import fs from "node:fs";
import { EventEmitter } from "node:events";

import type { HelperEvent } from "../shared/types";

export type HotkeyMode = "dictation" | "command";

export interface HelperEvents {
  press: (mode: HotkeyMode) => void;
  release: (mode: HotkeyMode) => void;
  toggle: (mode: HotkeyMode, on: boolean) => void;
  error: (message: string) => void;
  exit: (code: number | null) => void;
}

export class HelperManager extends EventEmitter {
  private proc: ChildProcess | null = null;
  private stdoutBuffer = "";

  private binaryPath(): string {
    // helper-mac and helper-win both produce a binary named miniflow-fn-helper;
    // Cargo on Windows appends .exe automatically.
    const exeName = process.platform === "win32" ? "miniflow-fn-helper.exe" : "miniflow-fn-helper";
    if (app.isPackaged) {
      return path.join(process.resourcesPath, exeName);
    }
    return path.resolve(
      __dirname, "..", "..", "..", "native-helper", "target", "release", exeName
    );
  }

  start(): void {
    const bin = this.binaryPath();
    if (!fs.existsSync(bin)) {
      const crate = process.platform === "win32" ? "helper-win" : "helper-mac";
      this.emit(
        "error",
        `helper binary missing at ${bin}. Run: cd native-helper && cargo build --release -p ${crate}`
      );
      return;
    }
    console.log(`[helper] spawning ${bin}`);
    this.proc = spawn(bin, [], { stdio: ["pipe", "pipe", "pipe"] });

    this.proc.stdout?.on("data", (d: Buffer) => this.onStdout(d.toString("utf8")));
    this.proc.stderr?.on("data", (d: Buffer) =>
      process.stderr.write(`[helper-err] ${d}`)
    );
    this.proc.on("exit", (code) => {
      console.log(`[helper] exited code=${code}`);
      this.emit("exit", code);
    });
  }

  private onStdout(text: string): void {
    this.stdoutBuffer += text;
    let newline = this.stdoutBuffer.indexOf("\n");
    while (newline !== -1) {
      const line = this.stdoutBuffer.slice(0, newline).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
      if (line) this.dispatch(line);
      newline = this.stdoutBuffer.indexOf("\n");
    }
  }

  private dispatch(line: string): void {
    let ev: any;
    try { ev = JSON.parse(line); }
    catch {
      this.emit("error", `helper emitted non-JSON: ${line}`);
      return;
    }
    // Rust serde internally-tagged enums serialize like:
    //   {"type":"press",   "mode":"dictation"}
    //   {"type":"release", "mode":"command"}
    //   {"type":"toggle",  "mode":"command", "on":true}
    //   {"type":"error",   "message":"ready"}
    const t = ev?.type;
    const mode: HotkeyMode = ev?.mode === "command" ? "command" : "dictation";
    if (t === "press") this.emit("press", mode);
    else if (t === "release") this.emit("release", mode);
    else if (t === "toggle") this.emit("toggle", mode, !!ev.on);
    else if (t === "error") {
      const msg = ev?.message ?? "unknown helper error";
      if (msg === "ready") console.log("[helper] ready");
      else this.emit("error", msg);
    } else {
      this.emit("error", `unrecognized helper line: ${line}`);
    }
  }

  type(text: string): void {
    if (!this.proc?.stdin || this.proc.stdin.destroyed) return;
    this.proc.stdin.write(JSON.stringify({ action: "type", text }) + "\n");
  }

  reload(): void {
    if (!this.proc?.stdin || this.proc.stdin.destroyed) return;
    this.proc.stdin.write(JSON.stringify({ action: "reload" }) + "\n");
  }

  quit(): void {
    if (this.proc?.stdin && !this.proc.stdin.destroyed) {
      this.proc.stdin.write(JSON.stringify({ action: "quit" }) + "\n");
    }
    this.proc?.kill("SIGTERM");
    this.proc = null;
  }
}

export const helper = new HelperManager();
