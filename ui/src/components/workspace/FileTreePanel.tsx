import { useMemo, useState, useRef, useCallback } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useWorkspaceFiles, useMoveWorkspaceFile, useWriteWorkspaceFile, useMkdirWorkspace } from "../../api/hooks/useWorkspaces";
import { FileTreeNode } from "./FileTreeNode";
import { FileContextMenu } from "./FileContextMenu";
import { ResizeHandle } from "./ResizeHandle";
import { Folder, FileText, Search, X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { ConfirmDialog } from "../shared/ConfirmDialog";

interface FileTreePanelProps {
  workspaceId: string;
  mobile?: boolean;
  indexedPaths?: Set<string>;
}

export function FileTreePanel({ workspaceId, mobile, indexedPaths }: FileTreePanelProps) {
  const t = useThemeTokens();
  const treeWidth = useFileBrowserStore((s) => s.treeWidth);
  const setTreeWidth = useFileBrowserStore((s) => s.setTreeWidth);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);
  const rightActive = useFileBrowserStore((s) => s.rightPane.activeFile);
  const closeFile = useFileBrowserStore((s) => s.closeFile);
  const [searchQuery, setSearchQuery] = useState("");
  const [rootDragOver, setRootDragOver] = useState(false);
  const [rootContextMenu, setRootContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [pendingRootMove, setPendingRootMove] = useState<{ src: string; srcName: string } | null>(null);
  const [creatingAtRoot, setCreatingAtRoot] = useState<{ type: "file" | "folder" } | null>(null);
  const [createName, setCreateName] = useState("");
  const rootDragCounter = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const createRef = useRef<HTMLInputElement>(null);
  const moveMutation = useMoveWorkspaceFile(workspaceId);
  const writeMutation = useWriteWorkspaceFile(workspaceId);
  const mkdirMutation = useMkdirWorkspace(workspaceId);

  const handleRootContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setRootContextMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const handleRootCreateIn = useCallback((_dir: string, type: "file" | "folder") => {
    setCreatingAtRoot({ type });
    setCreateName("");
  }, []);

  const commitRootCreate = useCallback(() => {
    const name = createName.trim();
    const type = creatingAtRoot?.type;
    setCreatingAtRoot(null);
    if (!name || !type) return;
    if (type === "folder") {
      mkdirMutation.mutate(name);
    } else {
      writeMutation.mutate({ path: name, content: "" });
    }
  }, [createName, creatingAtRoot, mkdirMutation, writeMutation]);

  const handleCreateKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRootCreate();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setCreatingAtRoot(null);
    }
  }, [commitRootCreate]);

  const { data, isLoading } = useWorkspaceFiles(workspaceId, "/");

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setSearchQuery("");
      searchRef.current?.blur();
    }
  }, []);

  const activePaths = useMemo(() => {
    const m: Record<string, boolean> = {};
    if (leftActive) m[leftActive] = true;
    if (rightActive) m[rightActive] = true;
    return m;
  }, [leftActive, rightActive]);

  const sortedEntries = useMemo(() => {
    if (!data?.entries) return [];
    return [...data.entries].sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [data?.entries]);

  const treeContent = (
    <div
      style={{
        width: mobile ? "100%" : treeWidth,
        height: "100%",
        overflow: "auto",
        background: t.surface,
        borderRight: mobile ? "none" : `1px solid ${t.surfaceBorder}`,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 6,
          padding: "10px 12px 8px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          flexShrink: 0,
        }}
      >
        <Folder size={14} color={t.textDim} />
        <span style={{ fontSize: 11, color: t.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>
          Explorer
        </span>
      </div>

      {/* Search */}
      <div style={{ padding: "6px 8px", borderBottom: `1px solid ${t.surfaceBorder}`, flexShrink: 0 }}>
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 4,
            background: t.inputBg,
            borderRadius: 4,
            padding: "4px 8px",
            border: `1px solid ${t.inputBorder}`,
          }}
        >
          <Search size={12} color={t.textDim} style={{ flexShrink: 0 }} />
          <input
            ref={searchRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Filter files..."
            style={{
              flex: 1,
              background: "none",
              border: "none",
              outline: "none",
              color: t.inputText,
              fontSize: 12,
              padding: 0,
              minWidth: 0,
            }}
          />
          {searchQuery && (
            <X
              size={12}
              color={t.textDim}
              style={{ cursor: "pointer", flexShrink: 0 }}
              onClick={() => { setSearchQuery(""); searchRef.current?.focus(); }}
            />
          )}
        </div>
      </div>

      {/* Tree */}
      <div
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
        onDragEnter={(e) => { e.preventDefault(); rootDragCounter.current++; setRootDragOver(true); }}
        onDragLeave={() => { rootDragCounter.current--; if (rootDragCounter.current <= 0) { rootDragCounter.current = 0; setRootDragOver(false); } }}
        onDrop={(e) => {
          e.preventDefault();
          rootDragCounter.current = 0;
          setRootDragOver(false);
          const srcPath = e.dataTransfer.getData("text/plain");
          if (!srcPath) return;
          // Don't move if already at root level (no directory separator beyond first segment)
          if (!srcPath.includes("/")) return;
          const srcName = srcPath.split("/").pop() || srcPath;
          setPendingRootMove({ src: srcPath, srcName });
        }}
        onContextMenu={handleRootContextMenu}
        style={{ flex: 1, overflow: "auto", padding: "4px 0", background: rootDragOver ? "rgba(20,184,166,0.06)" : undefined }}
      >
        {isLoading ? (
          <div style={{ padding: 16, color: t.textDim, fontSize: 12 }}>Loading...</div>
        ) : (
          <>
            {creatingAtRoot && (
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  paddingLeft: 8,
                  paddingRight: 8,
                  paddingTop: 3,
                  paddingBottom: 3,
                }}
              >
                <span style={{ width: 14, display: "inline-block" }} />
                {creatingAtRoot.type === "folder" ? (
                  <Folder size={14} color="#e2a855" />
                ) : (
                  <FileText size={14} color={t.textMuted} />
                )}
                <input
                  ref={createRef}
                  autoFocus
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  onKeyDown={handleCreateKeyDown}
                  onBlur={commitRootCreate}
                  placeholder={creatingAtRoot.type === "folder" ? "folder name" : "file name"}
                  style={{
                    flex: 1,
                    fontSize: 13,
                    color: t.inputText,
                    background: t.inputBg,
                    border: `1px solid ${t.inputBorder}`,
                    borderRadius: 3,
                    padding: "1px 4px",
                    outline: "none",
                    minWidth: 0,
                  }}
                />
              </div>
            )}
            {sortedEntries.length === 0 && !creatingAtRoot ? (
              <div style={{ padding: 16, color: t.textDim, fontSize: 12 }}>Empty workspace</div>
            ) : (
              sortedEntries.map((entry) => (
                <FileTreeNode
                  key={entry.path}
                  entry={entry}
                  workspaceId={workspaceId}
                  depth={0}
                  activePaths={activePaths}
                  searchFilter={searchQuery}
                  indexedPaths={indexedPaths}
                />
              ))
            )}
          </>
        )}
      </div>
      {rootContextMenu && (
        <FileContextMenu
          x={rootContextMenu.x}
          y={rootContextMenu.y}
          entry={null}
          workspaceId={workspaceId}
          onClose={() => setRootContextMenu(null)}
          onStartRename={() => {}}
          onCreateIn={handleRootCreateIn}
        />
      )}
      <ConfirmDialog
        open={pendingRootMove !== null}
        title="Move File"
        message={pendingRootMove ? `Move "${pendingRootMove.srcName}" to root?` : ""}
        confirmLabel="Move"
        variant="default"
        onConfirm={() => {
          if (pendingRootMove) {
            const src = pendingRootMove.src;
            moveMutation.mutate({ src, dst: "/" }, {
              onSuccess: () => { closeFile(src, "left"); closeFile(src, "right"); },
            });
          }
          setPendingRootMove(null);
        }}
        onCancel={() => setPendingRootMove(null)}
      />
    </div>
  );

  if (mobile) {
    return treeContent;
  }

  return (
    <div style={{ display: "flex", flexDirection: "row", height: "100%", flexShrink: 0 }}>
      {treeContent}
      <ResizeHandle
        direction="horizontal"
        onResize={(delta) => setTreeWidth(treeWidth + delta)}
      />
    </div>
  );
}
