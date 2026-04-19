import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { StreamingToast } from "./StreamingToast";
import { ApprovalToast } from "./ApprovalToast";
import { ToastHost } from "./ToastHost";
import { ActiveWorkflowsHud } from "./ActiveWorkflowsHud";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useChatStore } from "../../stores/chat";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";
import { usePresenceHeartbeat } from "../../hooks/usePresenceHeartbeat";
import { CommandPalette, useCommandPaletteShortcut } from "./CommandPalette";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const paletteOpen = useUIStore((s) => s.paletteOpen);
  const closePalette = useUIStore((s) => s.closePalette);
  useCommandPaletteShortcut();
  usePresenceHeartbeat();
  const { data: status } = useSystemStatus();
  const anyStreaming = useChatStore(
    (s) => Object.values(s.channels).some((ch) => Object.keys(ch.turns).length > 0),
  );

  // Record every page visit for command palette recents
  const location = useLocation();
  const recordPageVisit = useUIStore((s) => s.recordPageVisit);
  useEffect(() => {
    const href = location.pathname + (location.hash || "");
    recordPageVisit(href);
  }, [location.pathname, location.hash, recordPageVisit]);

  // Warn on tab close / refresh when a stream is active
  useEffect(() => {
    if (!anyStreaming) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [anyStreaming]);

  return (
    <div className="relative flex flex-col flex-1 bg-surface overflow-hidden h-full">
      {status?.paused && <SystemPauseBanner behavior={status.pause_behavior} />}
      <div className="flex flex-row flex-1 overflow-hidden">
        {/* Sidebar — desktop only. On mobile the palette is the nav surface. */}
        {columns !== "single" && <Sidebar />}

        {/* Center content — always visible */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          <Outlet />
        </div>

        {/* Detail panel — only on triple column when active */}
        {columns === "triple" && hasDetail && <DetailPanel />}

        {/* Streaming toast — shows when a background channel is processing */}
        <StreamingToast />

        {/* Approval toast — shows when new pending approvals arrive */}
        <ApprovalToast />

        {/* Global workflow HUD — shows when any workflow is actively running */}
        <ActiveWorkflowsHud />

        {/* Generic toast host — success/info/error messages */}
        <ToastHost />
      </div>

      {/* Global command palette (Cmd+K / Ctrl+K on desktop, hamburger on mobile) */}
      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </div>
  );
}
