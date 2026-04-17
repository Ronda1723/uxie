/**
 * @jest-environment jsdom
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HotkeySettings } from "../../src/renderer/components/HotkeyRecorder";

function installMockApi() {
  let hotkey: any = { mode: "hold_to_talk", modifier: "fn", key: null };
  const api = {
    getHotkey: jest.fn(async () => hotkey),
    setHotkey: jest.fn(async (hk: any) => { hotkey = hk; return hk; }),
    resetHotkey: jest.fn(async () => {
      hotkey = { mode: "hold_to_talk", modifier: "fn", key: null };
      return hotkey;
    }),
  };
  (window as any).miniflow = api;
  return api;
}

describe("HotkeySettings", () => {
  beforeEach(() => installMockApi());

  it("renders the current hotkey (default Fn)", async () => {
    render(<HotkeySettings />);
    await waitFor(() => expect(screen.getByText("Fn")).toBeInTheDocument());
  });

  it("reset button calls resetHotkey", async () => {
    const api = installMockApi();
    render(<HotkeySettings />);
    await screen.findByText("Fn");
    fireEvent.click(screen.getByText("Reset"));
    await waitFor(() => expect(api.resetHotkey).toHaveBeenCalled());
  });

  it("enters listening mode on recorder click", async () => {
    render(<HotkeySettings />);
    await screen.findByText("Fn");
    const recorder = screen.getByRole("button", { pressed: false });
    fireEvent.click(recorder);
    await waitFor(() =>
      expect(screen.getByText(/Press any combination/i)).toBeInTheDocument()
    );
  });

  it("captures ⌘ + Space and saves the hotkey", async () => {
    const api = installMockApi();
    render(<HotkeySettings />);
    await screen.findByText("Fn");
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    await waitFor(() => expect(screen.getByText(/Press any combination/i)).toBeInTheDocument());
    fireEvent.keyDown(window, { code: "Space", key: " ", metaKey: true });
    await waitFor(() =>
      expect(api.setHotkey).toHaveBeenCalledWith({
        mode: "hold_to_talk", modifier: "cmd", key: "space",
      })
    );
  });

  it("rejects a bare letter with no modifier", async () => {
    const api = installMockApi();
    render(<HotkeySettings />);
    await screen.findByText("Fn");
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    await screen.findByText(/Press any combination/i);
    fireEvent.keyDown(window, { code: "KeyA", key: "a" });
    await waitFor(() =>
      expect(screen.getByText(/must include exactly one modifier/i)).toBeInTheDocument()
    );
    expect(api.setHotkey).not.toHaveBeenCalled();
  });

  it("Escape cancels listening without saving", async () => {
    const api = installMockApi();
    render(<HotkeySettings />);
    await screen.findByText("Fn");
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    await screen.findByText(/Press any combination/i);
    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });
    await waitFor(() => expect(screen.getByText("Fn")).toBeInTheDocument());
    expect(api.setHotkey).not.toHaveBeenCalled();
  });
});
