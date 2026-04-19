import React, { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { HomeTab } from "./components/HomeTab";
import { DictionaryTab } from "./components/DictionaryTab";
import { SnippetsTab } from "./components/SnippetsTab";
import { SettingsModal } from "./components/SettingsModal";
import { Onboarding } from "./components/Onboarding";
import { useAudioCapture } from "./audio";

export type SidebarTab = "home" | "dictionary" | "snippets";

const ONBOARDING_DISMISSED_KEY = "miniflow.onboarded";

export function App() {
  const [tab, setTab] = useState<SidebarTab>("home");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [agentStatus, setAgentStatus] = useState<string>("idle");
  const [userName] = useState<string>("");
  const { capturing, mode: captureMode } = useAudioCapture();
  const isListening = capturing;
  const isProcessing = agentStatus === "processing";

  // Decide whether to show onboarding on mount: show if any permission is not
  // granted AND the user hasn't already dismissed it.
  useEffect(() => {
    (async () => {
      const dismissed = localStorage.getItem(ONBOARDING_DISMISSED_KEY) === "1";
      try {
        const perms = (await (window.miniflow as any).getPermissions()) as { status: string }[];
        const anyMissing = perms.some((p) => p.status !== "granted");
        if (anyMissing && !dismissed) setShowOnboarding(true);
      } catch { /* ignore */ }
    })();
  }, []);

  useEffect(() => {
    const offStatus = window.miniflow.onAgentStatus((s) => setAgentStatus(s));
    const offAct = window.miniflow.onAction((a) => {
      if (a.action === "dictation" && a.success) {
        window.miniflow.requestType(a.message);
      }
    });
    return () => { offStatus(); offAct(); };
  }, []);

  function closeOnboarding() {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
    setShowOnboarding(false);
  }

  return (
    <div className="app">
      <Sidebar
        activeTab={tab}
        onTab={setTab}
        isListening={isListening}
        onSettings={() => setSettingsOpen(true)}
      />
      <div className="content-wrap">
        <div className="content">
          {tab === "home" && (
            <HomeTab
              userName={userName}
              isListening={isListening}
              isProcessing={isProcessing}
              captureMode={captureMode}
            />
          )}
          {tab === "dictionary" && <DictionaryTab />}
          {tab === "snippets"   && <SnippetsTab />}
        </div>
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {showOnboarding && <Onboarding onDone={closeOnboarding} />}
    </div>
  );
}

function EmptyTab({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="home">
      <h1>{title}</h1>
      <p className="info-msg">{hint}</p>
    </div>
  );
}
