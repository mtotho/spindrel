import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Terminal as TerminalIcon, X as CloseIcon } from "lucide-react";

import { useWorkspaceIndexStatus } from "@/src/api/hooks/useWorkspaces";
import type { SharedWorkspace } from "@/src/types/api";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useThemeTokens } from "@/src/theme/tokens";
import { BrowserToolbar } from "./BrowserToolbar";
import { FileTreePanel } from "./FileTreePanel";
import { SplitViewContainer } from "./SplitViewContainer";
import { UploadDialog } from "./UploadDialog";

const MOBILE_BREAKPOINT = 768;
const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

function normalizeRootPath(path: string | null | undefined): string {
  const stripped = (path ?? "").replace(/^\/+|\/+$/g, "");
  return stripped ? stripped : "";
}

function dirForActiveFile(activeFile: string | null, fallbackRoot: string): string {
  if (!activeFile) return fallbackRoot;
  const dir = activeFile.substring(0, activeFile.lastIndexOf("/"));
  return dir || fallbackRoot;
}

export interface WorkspaceFileBrowserSurfaceProps {
  workspace: SharedWorkspace;
  rootPath?: string | null;
  rootLabel?: string;
  settingsHref?: string;
  title?: string;
  className?: string;
  onOpenTerminal?: (workspaceRelativePath: string) => void;
}

export function WorkspaceFileBrowserSurface({
  workspace,
  rootPath,
  rootLabel = "Workspace",
  settingsHref,
  title,
  className,
  onOpenTerminal,
}: WorkspaceFileBrowserSurfaceProps) {
  const t = useThemeTokens();
  const reset = useFileBrowserStore((s) => s.reset);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);
  const treeVisible = useFileBrowserStore((s) => s.treeVisible);
  const hideTree = useFileBrowserStore((s) => s.hideTree);
  const expandDir = useFileBrowserStore((s) => s.expandDir);

  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_BREAKPOINT;
  const scopedRoot = useMemo(() => normalizeRootPath(rootPath), [rootPath]);
  const rootApiPath = scopedRoot ? `/${scopedRoot}` : "/";

  const [showUpload, setShowUpload] = useState(false);
  const [terminalRequest, setTerminalRequest] = useState<{ cwd: string; label: string } | null>(null);
  const { data: indexData } = useWorkspaceIndexStatus(workspace.id);

  const { indexedPaths, indexMap } = useMemo(() => {
    const files = indexData?.indexed_files ?? {};
    const paths = new Set<string>();
    for (const p of Object.keys(files)) {
      paths.add(p);
      const parts = p.split("/");
      for (let i = 1; i < parts.length; i += 1) {
        paths.add(parts.slice(0, i).join("/"));
      }
    }
    return { indexedPaths: paths, indexMap: files };
  }, [indexData?.indexed_files]);

  useEffect(() => {
    reset();
    if (scopedRoot) {
      const parts = scopedRoot.split("/");
      for (let i = 1; i <= parts.length; i += 1) {
        expandDir(parts.slice(0, i).join("/"));
      }
    }
    return () => reset();
  }, [expandDir, reset, scopedRoot, workspace.id]);

  useEffect(() => {
    if (isMobile && leftActive) {
      hideTree();
    }
  }, [hideTree, isMobile, leftActive]);

  const currentDir = dirForActiveFile(leftActive, scopedRoot);

  const openTerminalAtPath = (workspaceRelativePath: string) => {
    const trimmed = (workspaceRelativePath || scopedRoot).replace(/^\/+|\/+$/g, "");
    if (onOpenTerminal) {
      onOpenTerminal(trimmed);
      return;
    }
    setTerminalRequest({
      cwd: `workspace://${workspace.id}${trimmed ? `/${trimmed}` : ""}`,
      label: trimmed ? `/${trimmed}` : "/",
    });
  };

  return (
    <div
      className={className}
      style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, minHeight: 0 }}
    >
      <BrowserToolbar
        workspace={workspace}
        title={title}
        rootPath={scopedRoot}
        rootLabel={rootLabel}
        settingsHref={settingsHref}
        onUpload={() => setShowUpload(true)}
        onOpenTerminal={openTerminalAtPath}
        isMobile={isMobile}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden", position: "relative", minHeight: 0 }}>
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
              <FileTreePanel workspaceId={workspace.id} rootPath={rootApiPath} rootLabel={rootLabel} mobile indexedPaths={indexedPaths} />
            </div>
          </>
        )}

        {!isMobile && treeVisible && (
          <FileTreePanel workspaceId={workspace.id} rootPath={rootApiPath} rootLabel={rootLabel} indexedPaths={indexedPaths} />
        )}

        <SplitViewContainer workspaceId={workspace.id} indexMap={indexMap} />
      </div>

      {showUpload && (
        <UploadDialog
          workspaceId={workspace.id}
          currentDir={currentDir ? `/${currentDir}` : "/"}
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
