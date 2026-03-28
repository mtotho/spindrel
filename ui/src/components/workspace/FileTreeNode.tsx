import { ChevronRight, ChevronDown, FileText, Folder, FolderOpen, Trash2 } from "lucide-react";
import { useState, useMemo, useCallback, useRef } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useWorkspaceFiles, useDeleteWorkspaceFile, useMoveWorkspaceFile } from "../../api/hooks/useWorkspaces";
import type { WorkspaceFileEntry } from "../../types/api";

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

interface FileTreeNodeProps {
  entry: WorkspaceFileEntry;
  workspaceId: string;
  depth: number;
  activePaths: Record<string, boolean>;
  searchFilter?: string;
  indexedPaths?: Set<string>;
}

export function FileTreeNode({ entry, workspaceId, depth, activePaths, searchFilter, indexedPaths }: FileTreeNodeProps) {
  const [hovered, setHovered] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const dragCounter = useRef(0);
  const expanded = useFileBrowserStore((s) => !!s.expandedDirs[entry.path]);
  const toggleDir = useFileBrowserStore((s) => s.toggleDir);
  const openFile = useFileBrowserStore((s) => s.openFile);
  const closeFile = useFileBrowserStore((s) => s.closeFile);
  const splitMode = useFileBrowserStore((s) => s.splitMode);

  const { data: children } = useWorkspaceFiles(workspaceId, entry.path);
  const deleteMutation = useDeleteWorkspaceFile(workspaceId);
  const moveMutation = useMoveWorkspaceFile(workspaceId);

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
    // Can't drop a dir into its own child
    if (entry.path.startsWith(srcPath + "/")) return;
    moveMutation.mutate({ src: srcPath, dst: entry.path }, {
      onSuccess: () => {
        closeFile(srcPath, "left");
        closeFile(srcPath, "right");
      },
    });
  }, [entry.path, entry.is_dir, moveMutation, closeFile]);

  // Search filter visibility
  const nameMatches = !searchFilter || fuzzyMatch(searchFilter, entry.name);

  const hasMatchingChildren = useMemo(() => {
    if (!searchFilter || !entry.is_dir) return false;
    if (!children?.entries) return true; // not loaded yet, assume visible
    return children.entries.some((child) => {
      if (fuzzyMatch(searchFilter, child.name)) return true;
      if (child.is_dir) return true; // subdirs might have deeper matches
      return false;
    });
  }, [searchFilter, entry.is_dir, children?.entries]);

  if (searchFilter) {
    if (!entry.is_dir && !nameMatches) return null;
    if (entry.is_dir && !nameMatches && !hasMatchingChildren) return null;
  }

  // Auto-expand directories when filtering
  const effectiveExpanded = entry.is_dir && (expanded || !!searchFilter);

  const isActive = !!activePaths[entry.path];

  const handleClick = () => {
    if (entry.is_dir) {
      toggleDir(entry.path);
    } else {
      openFile(entry.path, entry.name, "left");
    }
  };

  const handleOpenToSide = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!entry.is_dir) {
      openFile(entry.path, entry.name, "right");
    }
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`Delete ${entry.is_dir ? "folder" : "file"} "${entry.name}"?`)) {
      deleteMutation.mutate(entry.path);
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
        draggable
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => { setHovered(false); dragCounter.current = 0; setDragOver(false); }}
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
            : isActive ? "rgba(59,130,246,0.12)" : hovered ? "rgba(255,255,255,0.04)" : "transparent",
          borderLeft: dragOver ? "2px solid #14b8a6" : "2px solid transparent",
          borderRadius: 4,
          userSelect: "none",
        }}
      >
        {entry.is_dir ? (
          effectiveExpanded ? (
            <ChevronDown size={14} color="#666" />
          ) : (
            <ChevronRight size={14} color="#666" />
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
          <FileText size={14} color="#888" />
        )}

        <span
          style={{
            flex: 1,
            fontSize: 13,
            color: isActive ? "#e5e5e5" : "#aaa",
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

        {!hovered && !entry.is_dir && entry.modified_at && (
          <span style={{ fontSize: 10, color: "#444", flexShrink: 0, paddingRight: 4 }}>
            {formatTimestamp(entry.modified_at)}
          </span>
        )}

        {hovered && (
          <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
            {!entry.is_dir && splitMode && (
              <span
                onClick={handleOpenToSide}
                style={{ cursor: "pointer", padding: 2, opacity: 0.6 }}
                title="Open to side"
              >
                <FileText size={12} color="#888" />
              </span>
            )}
            <span
              onClick={handleDelete}
              style={{ cursor: "pointer", padding: 2, opacity: 0.6 }}
              title="Delete"
            >
              <Trash2 size={12} color="#ef4444" />
            </span>
          </div>
        )}
      </div>

      {entry.is_dir && effectiveExpanded && (
        <div>
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
    </div>
  );
}
