import { ChevronRight, ChevronDown, FileText, Folder, FolderOpen } from "lucide-react";
import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useWorkspaceFiles, useDeleteWorkspaceFile, useMoveWorkspaceFile, useWriteWorkspaceFile, useMkdirWorkspace } from "../../api/hooks/useWorkspaces";
import { FileContextMenu } from "./FileContextMenu";
import type { WorkspaceFileEntry } from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";

function fuzzyMatch(needle: string, haystack: string): boolean {
  if (!needle) return true;
  const n = needle.toLowerCase();
  const h = haystack.toLowerCase();
  let ni = 0;
  for (let hi = 0; hi < h.length && ni < n.length; hi++) {
    if (h[hi] === n[ni]) ni++;
  }
  return ni === n.length;
}

function formatTimestamp(ts: number | null | undefined): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const now = Date.now();
  const diffMs = now - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 30) return `${diffDays}d`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}K`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
}

/** Select filename without extension in an input */
function selectNameWithoutExt(input: HTMLInputElement) {
  const val = input.value;
  const dot = val.lastIndexOf(".");
  if (dot > 0) {
    input.setSelectionRange(0, dot);
  } else {
    input.select();
  }
}

interface FileTreeNodeProps {
  entry: WorkspaceFileEntry;
  workspaceId: string;
  depth: number;
  activePaths: Record<string, boolean>;
  searchFilter?: string;
  indexedPaths?: Set<string>;
  // Propagated from parent for root-level context menu coordination
  onContextMenu?: (e: React.MouseEvent, entry: WorkspaceFileEntry) => void;
}

export function FileTreeNode({ entry, workspaceId, depth, activePaths, searchFilter, indexedPaths }: FileTreeNodeProps) {
  const t = useThemeTokens();
  const [dragOver, setDragOver] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [creatingChild, setCreatingChild] = useState<{ type: "file" | "folder" } | null>(null);
  const [createName, setCreateName] = useState("");
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const dragCounter = useRef(0);
  const renameRef = useRef<HTMLInputElement>(null);
  const createRef = useRef<HTMLInputElement>(null);
  const expanded = useFileBrowserStore((s) => !!s.expandedDirs[entry.path]);
  const toggleDir = useFileBrowserStore((s) => s.toggleDir);
  const expandDir = useFileBrowserStore((s) => s.expandDir);
  const openFile = useFileBrowserStore((s) => s.openFile);
  const closeFile = useFileBrowserStore((s) => s.closeFile);

  const { data: children } = useWorkspaceFiles(workspaceId, entry.path);
  const deleteMutation = useDeleteWorkspaceFile(workspaceId);
  const moveMutation = useMoveWorkspaceFile(workspaceId);
  const writeMutation = useWriteWorkspaceFile(workspaceId);
  const mkdirMutation = useMkdirWorkspace(workspaceId);

  // Focus rename input when entering rename mode
  useEffect(() => {
    if (renaming && renameRef.current) {
      renameRef.current.focus();
      selectNameWithoutExt(renameRef.current);
    }
  }, [renaming]);

  // Focus create input
  useEffect(() => {
    if (creatingChild && createRef.current) {
      createRef.current.focus();
    }
  }, [creatingChild]);

  // Drag handlers
  const handleDragStart = useCallback((e: React.DragEvent) => {
    e.dataTransfer.setData("text/plain", entry.path);
    e.dataTransfer.effectAllowed = "move";
  }, [entry.path]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (!entry.is_dir) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, [entry.is_dir]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    if (!entry.is_dir) return;
    e.preventDefault();
    dragCounter.current++;
    setDragOver(true);
  }, [entry.is_dir]);

  const handleDragLeave = useCallback(() => {
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setDragOver(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragOver(false);
    if (!entry.is_dir) return;
    const srcPath = e.dataTransfer.getData("text/plain");
    if (!srcPath || srcPath === entry.path) return;
    if (entry.path.startsWith(srcPath + "/")) return;
    const srcName = srcPath.split("/").pop() || srcPath;
    if (!window.confirm(`Move "${srcName}" into "${entry.name}"?`)) return;
    moveMutation.mutate({ src: srcPath, dst: entry.path }, {
      onSuccess: () => {
        closeFile(srcPath, "left");
        closeFile(srcPath, "right");
      },
    });
  }, [entry.path, entry.name, entry.is_dir, moveMutation, closeFile]);

  // Search filter visibility
  const nameMatches = !searchFilter || fuzzyMatch(searchFilter, entry.name);

  const hasMatchingChildren = useMemo(() => {
    if (!searchFilter || !entry.is_dir) return false;
    if (!children?.entries) return true;
    return children.entries.some((child) => {
      if (fuzzyMatch(searchFilter, child.name)) return true;
      if (child.is_dir) return true;
      return false;
    });
  }, [searchFilter, entry.is_dir, children?.entries]);

  if (searchFilter) {
    if (!entry.is_dir && !nameMatches) return null;
    if (entry.is_dir && !nameMatches && !hasMatchingChildren) return null;
  }

  const effectiveExpanded = entry.is_dir && (expanded || !!searchFilter);
  const isActive = !!activePaths[entry.path];

  const handleClick = () => {
    if (renaming) return;
    if (entry.is_dir) {
      toggleDir(entry.path);
    } else {
      openFile(entry.path, entry.name, "left");
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY });
  };

  // Rename
  const startRename = (target: WorkspaceFileEntry) => {
    if (target.path !== entry.path) return;
    setRenameValue(target.name);
    setRenaming(true);
  };

  const commitRename = () => {
    const newName = renameValue.trim();
    setRenaming(false);
    if (!newName || newName === entry.name) return;
    const parentDir = entry.path.includes("/") ? entry.path.substring(0, entry.path.lastIndexOf("/")) : "";
    const newPath = parentDir ? parentDir + "/" + newName : newName;
    moveMutation.mutate({ src: entry.path, dst: newPath }, {
      onSuccess: () => {
        closeFile(entry.path, "left");
        closeFile(entry.path, "right");
      },
    });
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setRenaming(false);
    }
  };

  // Inline create
  const startCreate = (dir: string, type: "file" | "folder") => {
    if (dir !== entry.path || !entry.is_dir) return;
    if (!expanded) expandDir(entry.path);
    setCreatingChild({ type });
    setCreateName("");
  };

  const commitCreate = () => {
    const name = createName.trim();
    const type = creatingChild?.type;
    setCreatingChild(null);
    if (!name || !type) return;
    const newPath = entry.path === "/" ? name : entry.path + "/" + name;
    if (type === "folder") {
      mkdirMutation.mutate(newPath);
    } else {
      writeMutation.mutate({ path: newPath, content: "" });
    }
  };

  const handleCreateKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitCreate();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setCreatingChild(null);
    }
  };

  const sortedChildren = children?.entries
    ? [...children.entries].sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
    : [];

  return (
    <div>
      <div
        draggable={!renaming}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          paddingLeft: depth * 16 + 8,
          paddingRight: 8,
          paddingTop: 3,
          paddingBottom: 3,
          cursor: "pointer",
          background: dragOver
            ? "rgba(20,184,166,0.15)"
            : isActive ? `${t.accent}1f` : "transparent",
          borderLeft: dragOver ? "2px solid #14b8a6" : "2px solid transparent",
          borderRadius: 4,
          userSelect: "none",
        }}
      >
        {entry.is_dir ? (
          effectiveExpanded ? (
            <ChevronDown size={14} color={t.textDim} />
          ) : (
            <ChevronRight size={14} color={t.textDim} />
          )
        ) : (
          <span style={{ width: 14, display: "inline-block" }} />
        )}

        {entry.is_dir ? (
          effectiveExpanded ? (
            <FolderOpen size={14} color="#e2a855" />
          ) : (
            <Folder size={14} color="#e2a855" />
          )
        ) : (
          <FileText size={14} color={t.textMuted} />
        )}

        {renaming ? (
          <input
            ref={renameRef}
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={handleRenameKeyDown}
            onBlur={commitRename}
            onClick={(e) => e.stopPropagation()}
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
        ) : (
          <span
            style={{
              flex: 1,
              fontSize: 13,
              color: isActive ? t.text : t.textMuted,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {entry.name}
            {indexedPaths?.has(entry.path) && (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "#14b8a6",
                  flexShrink: 0,
                }}
                title="Indexed"
              />
            )}
          </span>
        )}

        {!renaming && !entry.is_dir && (
          <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0, paddingRight: 4, whiteSpace: "nowrap" }}>
            {[formatSize(entry.size), formatTimestamp(entry.modified_at)].filter(Boolean).join(" · ")}
          </span>
        )}
      </div>

      {entry.is_dir && effectiveExpanded && (
        <div>
          {creatingChild && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                paddingLeft: (depth + 1) * 16 + 8,
                paddingRight: 8,
                paddingTop: 3,
                paddingBottom: 3,
              }}
            >
              <span style={{ width: 14, display: "inline-block" }} />
              {creatingChild.type === "folder" ? (
                <Folder size={14} color="#e2a855" />
              ) : (
                <FileText size={14} color={t.textMuted} />
              )}
              <input
                ref={createRef}
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                onKeyDown={handleCreateKeyDown}
                onBlur={commitCreate}
                placeholder={creatingChild.type === "folder" ? "folder name" : "file name"}
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
          {sortedChildren.map((child) => (
            <FileTreeNode
              key={child.path}
              entry={child}
              workspaceId={workspaceId}
              depth={depth + 1}
              activePaths={activePaths}
              searchFilter={searchFilter}
              indexedPaths={indexedPaths}
            />
          ))}
        </div>
      )}

      {contextMenu && (
        <FileContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          entry={entry}
          workspaceId={workspaceId}
          onClose={() => setContextMenu(null)}
          onStartRename={startRename}
          onCreateIn={startCreate}
        />
      )}
    </div>
  );
}
