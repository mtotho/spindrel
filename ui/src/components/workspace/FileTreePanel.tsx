import { useMemo } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useWorkspaceFiles } from "../../api/hooks/useWorkspaces";
import { FileTreeNode } from "./FileTreeNode";
import { ResizeHandle } from "./ResizeHandle";
import { Folder } from "lucide-react";

interface FileTreePanelProps {
  workspaceId: string;
}

export function FileTreePanel({ workspaceId }: FileTreePanelProps) {
  const treeWidth = useFileBrowserStore((s) => s.treeWidth);
  const setTreeWidth = useFileBrowserStore((s) => s.setTreeWidth);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);
  const rightActive = useFileBrowserStore((s) => s.rightPane.activeFile);

  const { data, isLoading } = useWorkspaceFiles(workspaceId, "/");

  const activePaths = useMemo(() => {
    const s = new Set<string>();
    if (leftActive) s.add(leftActive);
    if (rightActive) s.add(rightActive);
    return s;
  }, [leftActive, rightActive]);

  const sortedEntries = useMemo(() => {
    if (!data?.entries) return [];
    return [...data.entries].sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [data?.entries]);

  return (
    <div style={{ display: "flex", flexDirection: "row", height: "100%", flexShrink: 0 }}>
      <div
        style={{
          width: treeWidth,
          height: "100%",
          overflow: "auto",
          background: "#111",
          borderRight: "1px solid #222",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 12px 8px",
            borderBottom: "1px solid #1a1a1a",
            flexShrink: 0,
          }}
        >
          <Folder size={14} color="#666" />
          <span style={{ fontSize: 11, color: "#666", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1 }}>
            Explorer
          </span>
        </div>

        {/* Tree */}
        <div style={{ flex: 1, overflow: "auto", padding: "4px 0" }}>
          {isLoading ? (
            <div style={{ padding: 16, color: "#555", fontSize: 12 }}>Loading...</div>
          ) : sortedEntries.length === 0 ? (
            <div style={{ padding: 16, color: "#555", fontSize: 12 }}>Empty workspace</div>
          ) : (
            sortedEntries.map((entry) => (
              <FileTreeNode
                key={entry.path}
                entry={entry}
                workspaceId={workspaceId}
                depth={0}
                activePaths={activePaths}
              />
            ))
          )}
        </div>
      </div>

      <ResizeHandle
        direction="horizontal"
        onResize={(delta) => setTreeWidth(treeWidth + delta)}
      />
    </div>
  );
}
