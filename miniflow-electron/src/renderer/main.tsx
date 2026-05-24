import * as Sentry from "@sentry/electron/renderer";
Sentry.init({});  // shares DSN + config with the main-process init

import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { err: Error | null }
> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  componentDidCatch(err: Error, info: unknown) {
    console.error("[renderer]", err, info);
    Sentry.captureException(err, { extra: { info } });
  }
  render() {
    if (this.state.err) {
      const err = this.state.err as Error;
      return (
        <div style={{ padding: 24, fontFamily: "monospace", fontSize: 12, color: "#9B1C1C", whiteSpace: "pre-wrap" }}>
          <strong>Renderer crashed:</strong>{"\n"}
          {err.message}{"\n\n"}
          {err.stack || ""}
        </div>
      );
    }
    return this.props.children;
  }
}

window.addEventListener("error", (e) => console.error("[window.error]", e.error || e.message));
window.addEventListener("unhandledrejection", (e) => console.error("[unhandledrejection]", e.reason));

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");
createRoot(root).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
