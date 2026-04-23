/**
 * @jest-environment node
 *
 * Unit test for HelperManager's stdout line parser. We exercise the private
 * dispatch function by spawning a fake child proxy and driving the events.
 */

import { EventEmitter } from "node:events";

jest.mock("node:child_process", () => ({
  spawn: jest.fn(),
}));
jest.mock("electron", () => ({
  app: { isPackaged: false },
}));

import { spawn } from "node:child_process";
import { HelperManager } from "../../src/main/helper";

function fakeProc() {
  const proc = new EventEmitter() as any;
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.stdin = { write: jest.fn(), destroyed: false };
  proc.kill = jest.fn();
  return proc;
}

describe("HelperManager.dispatch", () => {
  beforeEach(() => {
    (spawn as jest.Mock).mockReset();
    jest.spyOn(require("node:fs"), "existsSync").mockReturnValue(true);
  });

  it("emits 'press' on press event", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    const onPress = jest.fn();
    h.on("press", onPress);
    h.start();
    proc.stdout.emit("data", Buffer.from('{"press":true}\n'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("emits 'release' on release event", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    const onRelease = jest.fn();
    h.on("release", onRelease);
    h.start();
    proc.stdout.emit("data", Buffer.from('{"release":true}\n'));
    expect(onRelease).toHaveBeenCalledTimes(1);
  });

  it("emits 'toggle' with on/off", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    const onToggle = jest.fn();
    h.on("toggle", onToggle);
    h.start();
    proc.stdout.emit("data", Buffer.from('{"toggle":true,"on":true}\n'));
    proc.stdout.emit("data", Buffer.from('{"toggle":true,"on":false}\n'));
    expect(onToggle).toHaveBeenNthCalledWith(1, true);
    expect(onToggle).toHaveBeenNthCalledWith(2, false);
  });

  it("handles partial lines (buffered correctly)", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    const onPress = jest.fn();
    h.on("press", onPress);
    h.start();
    proc.stdout.emit("data", Buffer.from('{"pre'));
    expect(onPress).not.toHaveBeenCalled();
    proc.stdout.emit("data", Buffer.from('ss":true}\n'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("type() writes a JSON command to stdin", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    h.start();
    h.type("hello");
    expect(proc.stdin.write).toHaveBeenCalledWith('{"action":"type","text":"hello"}\n');
  });

  it("bad JSON triggers error event, not crash", () => {
    const h = new HelperManager();
    const proc = fakeProc();
    (spawn as jest.Mock).mockReturnValue(proc);
    const onError = jest.fn();
    h.on("error", onError);
    h.start();
    proc.stdout.emit("data", Buffer.from('not-json-at-all\n'));
    expect(onError).toHaveBeenCalled();
  });
});
