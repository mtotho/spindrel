import { ChevronRight, ChevronDown, FileText, Folder, FolderOpen, Trash2 } from "lucide-react";
import { useState, useMemo } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useWorkspaceFiles, useDeleteWorkspaceFile } from "../../api/hooks/useWorkspaces";
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
}

export function FileTreeNode({ entry, workspaceId, depth, activePaths, searchFilter }: FileTreeNodeProps) {
  const [hovered, setHovered] = useState(false);
  const expanded = useFileBrowserStore((s) => !!s.expandedDirs[entry.path]);
  const toggleDir = useFileBrowserStore((s) => s.toggleDir);
  const openFile = useFileBrowserStore((s) => s.openFile);
  const splitMode = useFileBrowserStore((s) => s.splitMode);

  const { data: children } = useWorkspaceFiles(workspaceId, entry.path);
  const deleteMutation = useDeleteWorkspaceFile(workspaceId);

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
        onClick={handleClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          paddingLeft: depth * 16 + 8,
          paddingRight: 8,
          paddingTop: 3,
          paddingBottom: 3,
          cursor: "pointer",
          background: isActive ? "rgba(59,130,246,0.12)" : hovered ? "rgba(255,255,255,0.04)" : "transparent",
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
          }}
        >
          {entry.name}
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
            />
          ))}
        </div>
      )}
    </div>
  );
}
