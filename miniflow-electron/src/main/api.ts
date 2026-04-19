// Thin HTTP wrapper around the Python backend at localhost:8765.
// Every backend command is exposed via POST /invoke/<command>.

const BASE = "http://127.0.0.1:8765";

export async function invoke<T = unknown>(
  command: string,
  body: Record<string, unknown> = {}
): Promise<T> {
  const resp = await fetch(`${BASE}/invoke/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`[${command}] HTTP ${resp.status}`);
  }
  const data = (await resp.json()) as { error?: string } & T;
  if ((data as any)?.error) {
    throw new Error(`[${command}] ${(data as any).error}`);
  }
  return data as T;
}

export async function waitUntilHealthy(timeoutMs = 15000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${BASE}/health`);
      if (r.ok) return;
    } catch {
      // engine not ready yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("Python backend failed to become healthy in time");
}

export const BACKEND_URL = BASE;
export const WS_URL = "ws://127.0.0.1:8765/ws";
