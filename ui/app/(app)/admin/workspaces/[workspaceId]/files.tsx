import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { lazy, Suspense, useState, useEffect, useMemo } from "react";

import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Terminal as TerminalIcon, X as CloseIcon } from "lucide-react";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useWorkspace, useWorkspaceIndexStatus } from "@/src/api/hooks/useWorkspaces";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useThemeTokens } from "@/src/theme/tokens";
import { BrowserToolbar } from "@/src/components/workspace/BrowserToolbar";
import { FileTreePanel } from "@/src/components/workspace/FileTreePanel";
import { SplitViewContainer } from "@/src/components/workspace/SplitViewContainer";
import { UploadDialog } from "@/src/components/workspace/UploadDialog";

const MOBILE_BREAKPOINT = 768;
const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

export default function WorkspaceFileBrowser() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams] = useSearchParams();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const reset = useFileBrowserStore((s) => s.reset);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);
  const treeVisible = useFileBrowserStore((s) => s.treeVisible);
  const hideTree = useFileBrowserStore((s) => s.hideTree);
  const expandDir = useFileBrowserStore((s) => s.expandDir);

  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_BREAKPOINT;

  const [showUpload, setShowUpload] = useState(false);
  const [terminalRequest, setTerminalRequest] = useState<{ cwd: string; label: string } | null>(null);
  const { data: indexData } = useWorkspaceIndexStatus(workspaceId);

  // Build set of indexed paths (including ancestor directories for teal dot on folders)
  const { indexedPaths, indexMap } = useMemo(() => {
    const files = indexData?.indexed_files ?? {};
    const paths = new Set<string>();
    for (const p of Object.keys(files)) {
      paths.add(p);
      // Add ancestor dirs
      const parts = p.split("/");
      for (let i = 1; i < parts.length; i++) {
        paths.add(parts.slice(0, i).join("/"));
      }
    }
    return { indexedPaths: paths, indexMap: files };
  }, [indexData?.indexed_files]);

  // Reset store when workspace changes
  useEffect(() => {
    reset();
    return () => reset();
  }, [workspaceId]);

  useEffect(() => {
    const requestedPath = searchParams.get("path");
    if (!requestedPath) return;
    const normalized = requestedPath.replace(/^\/+|\/+$/g, "");
    if (!normalized) return;
    const parts = normalized.split("/");
    for (let i = 1; i <= parts.length; i += 1) {
      expandDir(parts.slice(0, i).join("/"));
    }
  }, [expandDir, searchParams]);

  // On mobile, auto-hide tree when a file is opened
  useEffect(() => {
    if (isMobile && leftActive) {
      hideTree();
    }
  }, [leftActive, isMobile]);

  if (isLoading || !workspace) {
    return (
      <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.surface }}>
        <Spinner />
      </div>
    );
  }

  // Current directory for upload dialog
  const currentDir = leftActive ? leftActive.substring(0, leftActive.lastIndexOf("/")) || "/" : "/";
  const openTerminalAtPath = (workspaceRelativePath: string) => {
    if (!workspaceId) return;
    const trimmed = (workspaceRelativePath || "/").replace(/^\/+|\/+$/g, "");
    setTerminalRequest({
      cwd: `workspace://${workspaceId}${trimmed ? `/${trimmed}` : ""}`,
      label: trimmed ? `/${trimmed}` : "/",
    });
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, height: "100%" }}>
      {isMobile && <PageHeader variant="detail" title="Workspace" backTo={`/admin/workspaces/${workspaceId}`} />}
      <BrowserToolbar
        workspace={workspace}
        onUpload={() => setShowUpload(true)}
        onOpenTerminal={openTerminalAtPath}
        isMobile={isMobile}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden", position: "relative" }}>
        {/* Mobile overlay tree */}
        {isMobile && treeVisible && (
          <>
            <div
              onClick={hideTree}
              style={{
                position: "absolute",
                inset: 0,
                background: "rgba(0,0,0,0.5)",
                zIndex: 20,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                zIndex: 21,
                width: Math.min(280, windowWidth * 0.8),
              }}
            >
              <FileTreePanel workspaceId={workspace.id} mobile indexedPaths={indexedPaths} />
            </div>
          </>
        )}

        {/* Desktop inline tree */}
        {!isMobile && treeVisible && (
          <FileTreePanel workspaceId={workspace.id} indexedPaths={indexedPaths} />
        )}

        <SplitViewContainer workspaceId={workspace.id} indexMap={indexMap} />
      </div>

      {showUpload && (
        <UploadDialog
          workspaceId={workspace.id}
          currentDir={currentDir}
          onClose={() => setShowUpload(false)}
        />
      )}
      {terminalRequest && (
        <WorkspaceTerminalDrawer
          cwd={terminalRequest.cwd}
          label={terminalRequest.label}
          onClose={() => setTerminalRequest(null)}
        />
      )}
    </div>
  );
}

function WorkspaceTerminalDrawer({
  cwd,
  label,
  onClose,
}: {
  cwd: string;
  label: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-y-0 right-0 z-[10035] flex w-[min(820px,92vw)] flex-col border-l border-surface-border bg-[#0a0d12] shadow-2xl">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/10 bg-[#0d1117] px-3">
        <TerminalIcon size={15} className="text-accent" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-semibold text-zinc-200">Terminal</div>
          <div className="truncate font-mono text-[10px] text-zinc-500">{label}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1.5 text-zinc-500 hover:bg-white/10 hover:text-zinc-200"
          aria-label="Close terminal"
          title="Close terminal"
        >
          <CloseIcon size={14} />
        </button>
      </div>
      <Suspense fallback={<div className="flex flex-1 items-center justify-center bg-[#0a0d12] text-[12px] text-zinc-500">Starting terminal...</div>}>
        <TerminalPanel cwd={cwd} title={cwd} />
      </Suspense>
    </div>
  );
}
