import { useState } from "react";
import { useEnableEditor, useDisableEditor, useEditorStatus } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";
import { Toggle, Section } from "@/src/components/shared/FormControls";
import type { SharedWorkspace } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface EditorTabProps {
  workspace: SharedWorkspace;
  currentStatus: string;
}

// ---------------------------------------------------------------------------
// Editor tab: code-server toggle + status + open button
// ---------------------------------------------------------------------------
export function EditorTab({ workspace, currentStatus }: EditorTabProps) {
  const t = useThemeTokens();
  const enableMut = useEnableEditor(workspace.id);
  const disableMut = useDisableEditor(workspace.id);
  const { data: editorStatus } = useEditorStatus(workspace.id);
  const [opening, setOpening] = useState(false);

  const isRunning = currentStatus === "running";
  const editorEnabled = editorStatus?.editor_enabled ?? workspace.editor_enabled;
  const editorRunning = editorStatus?.editor_running ?? false;
  const busy = enableMut.isPending || disableMut.isPending;

  const handleToggle = () => {
    if (editorEnabled) {
      disableMut.mutate();
    } else {
      enableMut.mutate();
    }
  };

  const handleOpen = async () => {
    setOpening(true);
    try {
      await enableMut.mutateAsync();
      const { useAuthStore, getAuthToken } = await import("@/src/stores/auth");
      const { serverUrl } = useAuthStore.getState();
      const token = getAuthToken();
      const url = `${serverUrl}/api/v1/workspaces/${workspace.id}/editor/?tkn=${encodeURIComponent(token || "")}`;
      window.open(url, `editor-${workspace.id}`);
    } catch (err) {
      console.error("Failed to open editor:", err);
    } finally {
      setOpening(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Section title="Code Editor" description="Run VS Code (code-server) inside the workspace container. Enabling requires a container restart to map the editor port.">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Toggle
                value={editorEnabled}
                onChange={handleToggle}
                label={editorEnabled ? "Enabled" : "Disabled"}
              />
              {editorEnabled && (
                <span style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 4,
                  background: editorRunning ? t.successSubtle : "rgba(100,100,100,0.15)",
                  color: editorRunning ? t.success : "#999",
                  fontWeight: 600,
                }}>
                  {editorRunning ? "Running" : "Stopped"}
                </span>
              )}
            </div>
            {editorEnabled && isRunning && (
              <button
                onClick={handleOpen}
                disabled={opening}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  padding: "6px 14px", fontSize: 12, fontWeight: 600,
                  border: `1px solid ${t.accent}`, borderRadius: 6,
                  background: `${t.accent}15`, color: t.accent,
                  cursor: opening ? "not-allowed" : "pointer",
                }}
              >
                {opening ? "Opening..." : "Open Editor"}
              </button>
            )}
          </div>
          {editorEnabled && workspace.editor_port && (
            <div style={{ fontSize: 11, color: t.textDim }}>
              Port: {workspace.editor_port} (mapped to container:8443)
            </div>
          )}
          {!isRunning && editorEnabled && (
            <div style={{ fontSize: 11, color: t.warningMuted }}>
              Start the workspace to use the editor.
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}
