/**
 * @jest-environment node
 */
import { invoke, waitUntilHealthy } from "../../src/main/api";

describe("api.invoke", () => {
  beforeEach(() => {
    (global.fetch as any) = jest.fn();
  });
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("POSTs JSON and returns parsed body", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ connected: ["openai"] }),
    });
    const data = await invoke<{ connected: string[] }>("get_connected_providers");
    expect(data.connected).toEqual(["openai"]);
    const [url, opts] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toMatch("/invoke/get_connected_providers");
    expect(opts.method).toBe("POST");
  });

  it("throws on HTTP error status", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 });
    await expect(invoke("boom")).rejects.toThrow(/HTTP 500/);
  });

  it("throws on backend error field", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true, json: async () => ({ error: "nope" }),
    });
    await expect(invoke("boom")).rejects.toThrow(/nope/);
  });

  it("waitUntilHealthy resolves when /health returns ok", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true });
    await expect(waitUntilHealthy(1000)).resolves.toBeUndefined();
  });

  it("waitUntilHealthy rejects after timeout", async () => {
    (global.fetch as jest.Mock).mockRejectedValue(new Error("ECONNREFUSED"));
    await expect(waitUntilHealthy(300)).rejects.toThrow(/failed to become healthy/);
  });
});
