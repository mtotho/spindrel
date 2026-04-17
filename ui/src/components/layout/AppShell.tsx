import { useEffect, useState, useCallback } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { StreamingToast } from "./StreamingToast";
import { ApprovalToast } from "./ApprovalToast";
import { ActiveWorkflowsHud } from "./ActiveWorkflowsHud";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useChatStore } from "../../stores/chat";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";
import { CommandPalette, useCommandPaletteShortcut } from "./CommandPalette";
import { cn } from "../../lib/cn";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPaletteShortcut();
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
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

  // DEBUG: temporary viewport dimensions — remove after fixing bottom cutoff
  const [dbg, setDbg] = useState("");
  useEffect(() => {
    const update = () => {
      const vv = window.visualViewport;
      const root = document.getElementById("root");
      setDbg(
        `vh:${window.innerHeight} vv:${vv ? Math.round(vv.height) : "?"} root:${root ? root.clientHeight : "?"} body:${document.body.clientHeight} screen:${screen.height} dpr:${devicePixelRatio}`
      );
    };
    update();
    window.visualViewport?.addEventListener("resize", update);
    return () => window.visualViewport?.removeEventListener("resize", update);
  }, []);

  return (
    <div className="relative flex flex-col flex-1 bg-surface overflow-hidden h-full">
      {/* DEBUG: viewport info — remove after fixing bottom cutoff */}
      <div className="shrink-0 bg-danger text-white text-[10px] px-2 py-0.5 text-center z-50">{dbg}</div>
      {status?.paused && <SystemPauseBanner behavior={status.pause_behavior} />}
      <div className="flex flex-row flex-1 overflow-hidden">
        {/* Sidebar — hidden on single column (mobile), shown as overlay when toggled */}
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

        {/* Mobile sidebar drawer */}
        {columns === "single" && mounted && (
          <div
            className={cn(
              "absolute inset-0 z-[100] flex flex-row",
              visible ? "pointer-events-auto" : "pointer-events-none",
            )}
          >
            {/* Backdrop */}
            <div
              onClick={closeMobileSidebar}
              className={cn(
                "absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-250",
                visible ? "opacity-100" : "opacity-0",
              )}
            />
            {/* Sidebar panel — slides from left */}
            <div className={cn(
              "flex-1 z-[1] shadow-2xl transition-transform duration-300",
              visible
                ? "translate-x-0 ease-out"
                : "-translate-x-full ease-in",
            )}>
              <Sidebar mobile />
            </div>
          </div>
        )}
      </div>

      {/* Global command palette (Cmd+K / Ctrl+K) */}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
