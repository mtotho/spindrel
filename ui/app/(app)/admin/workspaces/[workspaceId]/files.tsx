import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useEffect, useMemo } from "react";

import { useParams, useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useWorkspace, useStartWorkspace, useWorkspaceIndexStatus } from "@/src/api/hooks/useWorkspaces";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useThemeTokens } from "@/src/theme/tokens";
import { BrowserToolbar } from "@/src/components/workspace/BrowserToolbar";
import { FileTreePanel } from "@/src/components/workspace/FileTreePanel";
import { SplitViewContainer } from "@/src/components/workspace/SplitViewContainer";
import { UploadDialog } from "@/src/components/workspace/UploadDialog";

const MOBILE_BREAKPOINT = 768;

export default function WorkspaceFileBrowser() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const startMutation = useStartWorkspace(workspaceId!);
  const reset = useFileBrowserStore((s) => s.reset);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);
  const treeVisible = useFileBrowserStore((s) => s.treeVisible);
  const hideTree = useFileBrowserStore((s) => s.hideTree);

  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_BREAKPOINT;

  const [showUpload, setShowUpload] = useState(false);
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

  // On mobile, auto-hide tree when a file is opened
  useEffect(() => {
    if (isMobile && leftActive) {
      hideTree();
    }
  }, [leftActive, isMobile]);

  if (isLoading || !workspace) {
    return (
      <div style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.surface }}>
        <Spinner />
      </div>
    );
  }

  const isRunning = workspace.status === "running";

  // Not-running state
  if (!isRunning) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, height: "100%" }}>
        {isMobile && <PageHeader variant="detail" title="Workspace" backTo={`/admin/workspaces/${workspaceId}`} />}
        <BrowserToolbar workspace={workspace} onUpload={() => setShowUpload(true)} isMobile={isMobile} />
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
          }}
        >
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 32,
              background: "rgba(100,100,100,0.1)",
              display: "flex", flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Play size={28} color={t.textDim} />
          </div>
          <span style={{ fontSize: 15, color: t.textMuted }}>
            Workspace is {workspace.status}
          </span>
          <button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending}
            style={{
              background: t.accent,
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "8px 20px",
              fontSize: 14,
              fontWeight: 600,
              cursor: startMutation.isPending ? "not-allowed" : "pointer",
            }}
          >
            {startMutation.isPending ? "Starting..." : "Start Workspace"}
          </button>
          {startMutation.error && (
            <span style={{ color: t.danger, fontSize: 12 }}>
              {startMutation.error.message}
            </span>
          )}
        </div>
      </div>
    );
  }

  // Current directory for upload dialog
  const currentDir = leftActive ? leftActive.substring(0, leftActive.lastIndexOf("/")) || "/" : "/";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, height: "100%" }}>
      {isMobile && <PageHeader variant="detail" title="Workspace" backTo={`/admin/workspaces/${workspaceId}`} />}
      <BrowserToolbar workspace={workspace} onUpload={() => setShowUpload(true)} isMobile={isMobile} />

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
    </div>
  );
}
