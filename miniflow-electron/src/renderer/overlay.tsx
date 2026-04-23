import React from "react";
import { createRoot } from "react-dom/client";
import { OverlayWidget } from "./components/OverlayWidget";

createRoot(document.getElementById("overlay-root")!).render(<OverlayWidget />);
