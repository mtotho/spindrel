import { useCallback, useRef } from "react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { FilePane } from "./FilePane";
import { ResizeHandle } from "./ResizeHandle";

interface SplitViewContainerProps {
  workspaceId: string;
}

export function SplitViewContainer({ workspaceId }: SplitViewContainerProps) {
  const splitMode = useFileBrowserStore((s) => s.splitMode);
  const splitRatio = useFileBrowserStore((s) => s.splitRatio);
  const setSplitRatio = useFileBrowserStore((s) => s.setSplitRatio);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleResize = useCallback(
    (delta: number) => {
      if (!containerRef.current) return;
      const totalWidth = containerRef.current.offsetWidth;
      if (totalWidth === 0) return;
      setSplitRatio(splitRatio + delta / totalWidth);
    },
    [splitRatio, setSplitRatio]
  );

  if (!splitMode) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <FilePane workspaceId={workspaceId} pane="left" />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden" }}
    >
      <div style={{ flex: splitRatio, display: "flex", overflow: "hidden", minWidth: 100 }}>
        <FilePane workspaceId={workspaceId} pane="left" />
      </div>
      <ResizeHandle direction="horizontal" onResize={handleResize} />
      <div style={{ flex: 1 - splitRatio, display: "flex", overflow: "hidden", minWidth: 100 }}>
        <FilePane workspaceId={workspaceId} pane="right" />
      </div>
    </div>
  );
}
