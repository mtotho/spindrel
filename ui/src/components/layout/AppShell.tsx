import { useEffect, useState, useCallback } from "react";
import { Slot } from "expo-router";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { StreamingToast } from "./StreamingToast";
import { ActiveWorkflowsHud } from "./ActiveWorkflowsHud";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useChatStore } from "../../stores/chat";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";
import { useThemeTokens } from "../../theme/tokens";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const { data: status } = useSystemStatus();
  const t = useThemeTokens();
  const anyStreaming = useChatStore(
    (s) => Object.values(s.channels).some((ch) => ch.isStreaming),
  );

  // Warn on tab close / refresh when a stream is active
  useEffect(() => {
    if (!anyStreaming) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [anyStreaming]);

  // Escape key closes mobile sidebar
  useEffect(() => {
    if (!mobileSidebarOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMobileSidebar();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [mobileSidebarOpen, closeMobileSidebar]);

  // Keep the overlay mounted during the exit animation, then unmount
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (mobileSidebarOpen) {
      setMounted(true);
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 300);
      return () => clearTimeout(timer);
    }
  }, [mobileSidebarOpen]);

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, backgroundColor: t.surface, overflow: "hidden", height: "100%" }}>
      {status?.paused && <SystemPauseBanner behavior={status.pause_behavior} />}
      <div style={{ display: "flex", flexDirection: "row", flex: 1, overflow: "hidden" }}>
        {/* Sidebar — hidden on single column (mobile), shown as overlay when toggled */}
        {columns !== "single" && <Sidebar />}

        {/* Center content — always visible */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <Slot />
        </div>

        {/* Detail panel — only on triple column when active */}
        {columns === "triple" && hasDetail && <DetailPanel />}

        {/* Streaming toast — shows when a background channel is processing */}
        <StreamingToast />

        {/* Global workflow HUD — shows when any workflow is actively running */}
        <ActiveWorkflowsHud />

        {/* Mobile sidebar drawer */}
        {columns === "single" && mounted && (
          <div
            style={{
              position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
              zIndex: 100, display: "flex", flexDirection: "row",
              pointerEvents: visible ? "auto" : "none",
            }}
          >
            {/* Backdrop */}
            <div
              onClick={closeMobileSidebar}
              style={{
                position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: "rgba(0,0,0,0.6)",
                backdropFilter: "blur(2px)",
                WebkitBackdropFilter: "blur(2px)",
                opacity: visible ? 1 : 0,
                transition: "opacity 250ms ease-out",
              }}
            />
            {/* Sidebar panel — slides from left */}
            <div style={{
              flex: 1, zIndex: 1,
              transform: visible ? "translateX(0)" : "translateX(-300px)",
              transition: visible
                ? "transform 280ms cubic-bezier(0.0, 0.0, 0.2, 1)"
                : "transform 280ms cubic-bezier(0.4, 0.0, 1, 1)",
            }}>
              <Sidebar mobile />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
