import { useEffect } from "react";
import { Outlet, useLocation, useSearchParams } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { StreamingToast } from "./StreamingToast";
import { ApprovalToast } from "./ApprovalToast";
import { ToastHost } from "./ToastHost";
import { TraceInspectorRoot } from "../shared/TraceInspector";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useChatStore } from "../../stores/chat";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";
import { usePresenceHeartbeat } from "../../hooks/usePresenceHeartbeat";
import { CommandPalette, useCommandPaletteShortcut } from "./CommandPalette";
import { KIOSK_PARAM } from "../../hooks/useKioskMode";
import { buildRecentHref } from "../../lib/recentPages";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const paletteOpen = useUIStore((s) => s.paletteOpen);
  const closePalette = useUIStore((s) => s.closePalette);
  // Kiosk mode reads the URL param directly — no hook dependency here so the
  // whole shell can still render even if the kiosk hook's effects would fail
  // (e.g. tests without react-router). Sole contract: hide every chrome
  // element when the param is set.
  const [searchParams] = useSearchParams();
  const kiosk = searchParams.get(KIOSK_PARAM) === "1";
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
    const href = buildRecentHref(location.pathname, location.search, location.hash);
    recordPageVisit(href);
  }, [location.pathname, location.search, location.hash, recordPageVisit]);

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
      {!kiosk && status?.paused && <SystemPauseBanner behavior={status.pause_behavior} />}
      <div className="flex flex-row flex-1 overflow-hidden">
        {/* Sidebar — desktop only. On mobile the palette is the nav surface.
            Suppressed in kiosk so the dashboard fills the viewport. */}
        {!kiosk && columns !== "single" && <Sidebar />}

        {/* Center content — always visible */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          <Outlet />
        </div>

        {/* Detail panel — only on triple column when active */}
        {!kiosk && columns === "triple" && hasDetail && <DetailPanel />}

        {/* All ambient chrome (toasts, HUDs) is suppressed in kiosk. The
            dashboard page owns its own exit affordance. */}
        {!kiosk && <StreamingToast />}
        {!kiosk && <ApprovalToast />}
        {!kiosk && <ToastHost />}
      </div>

      {/* Global command palette (Cmd+K / Ctrl+K on desktop, hamburger on mobile) */}
      {!kiosk && <CommandPalette open={paletteOpen} onClose={closePalette} />}
      {!kiosk && <TraceInspectorRoot />}
    </div>
  );
}
