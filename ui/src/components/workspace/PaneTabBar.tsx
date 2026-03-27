import { useFileBrowserStore, type PaneId, type OpenFile } from "../../stores/fileBrowser";
import { X } from "lucide-react";

interface PaneTabBarProps {
  pane: PaneId;
}

export function PaneTabBar({ pane }: PaneTabBarProps) {
  const paneState = useFileBrowserStore((s) => s[pane === "left" ? "leftPane" : "rightPane"]);
  const setActiveFile = useFileBrowserStore((s) => s.setActiveFile);
  const closeFile = useFileBrowserStore((s) => s.closeFile);

  if (paneState.openFiles.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        overflow: "auto",
        background: "#141414",
        borderBottom: "1px solid #222",
        flexShrink: 0,
        height: 34,
      }}
    >
      {paneState.openFiles.map((file) => {
        const isActive = paneState.activeFile === file.path;
        return (
          <div
            key={file.path}
            onClick={() => setActiveFile(file.path, pane)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "0 12px",
              cursor: "pointer",
              background: isActive ? "#1a1a1a" : "transparent",
              borderBottom: isActive ? "2px solid #3b82f6" : "2px solid transparent",
              borderRight: "1px solid #1a1a1a",
              whiteSpace: "nowrap",
              minWidth: 0,
              flexShrink: 0,
            }}
          >
            {file.dirty && (
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: "#f59e0b",
                  flexShrink: 0,
                }}
              />
            )}
            <span
              style={{
                fontSize: 12,
                color: isActive ? "#e5e5e5" : "#888",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {file.name}
            </span>
            <span
              onClick={(e) => {
                e.stopPropagation();
                closeFile(file.path, pane);
              }}
              style={{
                cursor: "pointer",
                padding: 2,
                borderRadius: 3,
                display: "flex",
                opacity: 0.5,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.opacity = "1")}
              onMouseLeave={(e) => (e.currentTarget.style.opacity = "0.5")}
            >
              <X size={12} color="#888" />
            </span>
          </div>
        );
      })}
    </div>
  );
}
