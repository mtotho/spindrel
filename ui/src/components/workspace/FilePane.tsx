import { useFileBrowserStore, type PaneId } from "../../stores/fileBrowser";
import { PaneTabBar } from "./PaneTabBar";
import { FileViewer } from "./FileViewer";
import { FileText } from "lucide-react";
import type { FileIndexEntry } from "../../api/hooks/useWorkspaces";
import { useThemeTokens } from "../../theme/tokens";

interface FilePaneProps {
  workspaceId: string;
  pane: PaneId;
  indexMap?: Record<string, FileIndexEntry>;
}

export function FilePane({ workspaceId, pane, indexMap }: FilePaneProps) {
  const t = useThemeTokens();
  const paneState = useFileBrowserStore((s) => s[pane === "left" ? "leftPane" : "rightPane"]);

  if (paneState.openFiles.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: t.surface,
          color: t.textDim,
          gap: 12,
        }}
      >
        <FileText size={40} color={t.textDim} />
        <span style={{ fontSize: 13 }}>Select a file to view</span>
        <span style={{ fontSize: 11, color: t.textDim }}>Click any file in the explorer</span>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <PaneTabBar pane={pane} />
      {paneState.activeFile && (
        <FileViewer
          key={`${pane}-${paneState.activeFile}`}
          workspaceId={workspaceId}
          filePath={paneState.activeFile}
          pane={pane}
          indexEntry={indexMap?.[paneState.activeFile]}
        />
      )}
    </div>
  );
}
