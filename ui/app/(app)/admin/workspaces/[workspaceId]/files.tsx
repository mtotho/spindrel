import { useState, useEffect } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Play } from "lucide-react";
import { useWorkspace, useStartWorkspace } from "@/src/api/hooks/useWorkspaces";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { BrowserToolbar } from "@/src/components/workspace/BrowserToolbar";
import { FileTreePanel } from "@/src/components/workspace/FileTreePanel";
import { SplitViewContainer } from "@/src/components/workspace/SplitViewContainer";
import { UploadDialog } from "@/src/components/workspace/UploadDialog";

export default function WorkspaceFileBrowser() {
  const { workspaceId } = useLocalSearchParams<{ workspaceId: string }>();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const startMutation = useStartWorkspace(workspaceId!);
  const reset = useFileBrowserStore((s) => s.reset);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);

  const [showUpload, setShowUpload] = useState(false);

  // Reset store when workspace changes
  useEffect(() => {
    reset();
    return () => reset();
  }, [workspaceId]);

  if (isLoading || !workspace) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#0d0d0d" }}>
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  const isRunning = workspace.status === "running";

  // Not-running state
  if (!isRunning) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#0d0d0d", height: "100%" }}>
        <BrowserToolbar workspace={workspace} onUpload={() => setShowUpload(true)} />
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
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Play size={28} color="#555" />
          </div>
          <span style={{ fontSize: 15, color: "#888" }}>
            Workspace is {workspace.status}
          </span>
          <button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending}
            style={{
              background: "#3b82f6",
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
            <span style={{ color: "#ef4444", fontSize: 12 }}>
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
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#0d0d0d", height: "100%" }}>
      <BrowserToolbar workspace={workspace} onUpload={() => setShowUpload(true)} />

      <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden" }}>
        <FileTreePanel workspaceId={workspace.id} />
        <SplitViewContainer workspaceId={workspace.id} />
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
