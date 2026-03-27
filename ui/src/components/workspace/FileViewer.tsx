import { useEffect, useRef } from "react";
import { useFileBrowserStore, type PaneId } from "../../stores/fileBrowser";
import { useWorkspaceFileContent, useWriteWorkspaceFile } from "../../api/hooks/useWorkspaces";
import { Save, X, Edit3, FileText } from "lucide-react";

interface FileViewerProps {
  workspaceId: string;
  filePath: string;
  pane: PaneId;
}

export function FileViewer({ workspaceId, filePath, pane }: FileViewerProps) {
  const { data, isLoading, error } = useWorkspaceFileContent(workspaceId, filePath);
  const writeMutation = useWriteWorkspaceFile(workspaceId);

  const paneState = useFileBrowserStore((s) => s[pane === "left" ? "leftPane" : "rightPane"]);
  const startEdit = useFileBrowserStore((s) => s.startEdit);
  const updateEdit = useFileBrowserStore((s) => s.updateEdit);
  const cancelEdit = useFileBrowserStore((s) => s.cancelEdit);
  const markClean = useFileBrowserStore((s) => s.markClean);

  const openFile = paneState.openFiles.find((f) => f.path === filePath);
  const isEditing = openFile?.editContent !== null && openFile?.editContent !== undefined;
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleStartEdit = () => {
    if (data?.content != null) {
      startEdit(filePath, pane, data.content);
    }
  };

  const handleSave = async () => {
    if (openFile?.editContent == null) return;
    try {
      await writeMutation.mutateAsync({ path: filePath, content: openFile.editContent });
      markClean(filePath, pane);
    } catch (e) {
      // error handled by mutation state
    }
  };

  const handleCancel = () => {
    cancelEdit(filePath, pane);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSave();
    }
    if (e.key === "Escape") {
      handleCancel();
    }
  };

  // Get file extension for basic syntax hint
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  const isBinary = error?.message?.includes("Binary") || data?.content === undefined && !isLoading && !error;

  if (isLoading) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>
        Loading...
      </div>
    );
  }

  if (error) {
    const msg = (error as any)?.body ? JSON.parse((error as any).body)?.detail : error.message;
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#ef4444", padding: 24 }}>
        <div style={{ textAlign: "center" }}>
          <FileText size={32} color="#555" style={{ marginBottom: 8 }} />
          <div style={{ fontSize: 13 }}>{msg || "Cannot display file"}</div>
        </div>
      </div>
    );
  }

  const content = data?.content ?? "";
  const lines = content.split("\n");

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 12px",
          borderBottom: "1px solid #222",
          background: "#0d0d0d",
          flexShrink: 0,
        }}
      >
        <span style={{ flex: 1, fontSize: 11, color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {filePath}
        </span>
        {isEditing ? (
          <>
            <button
              onClick={handleSave}
              disabled={writeMutation.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                background: "#22c55e", color: "#000", border: "none",
                borderRadius: 4, padding: "3px 10px", fontSize: 12,
                cursor: "pointer", fontWeight: 600,
              }}
            >
              <Save size={12} /> {writeMutation.isPending ? "Saving..." : "Save"}
            </button>
            <button
              onClick={handleCancel}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                background: "none", color: "#999", border: "1px solid #333",
                borderRadius: 4, padding: "3px 10px", fontSize: 12,
                cursor: "pointer",
              }}
            >
              <X size={12} /> Cancel
            </button>
          </>
        ) : (
          <button
            onClick={handleStartEdit}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: "none", color: "#999", border: "1px solid #333",
              borderRadius: 4, padding: "3px 10px", fontSize: 12,
              cursor: "pointer",
            }}
          >
            <Edit3 size={12} /> Edit
          </button>
        )}
        {data?.size != null && (
          <span style={{ fontSize: 11, color: "#555" }}>
            {data.size > 1024 ? `${(data.size / 1024).toFixed(1)}KB` : `${data.size}B`}
          </span>
        )}
      </div>

      {/* Content */}
      {isEditing ? (
        <textarea
          ref={textareaRef}
          value={openFile?.editContent ?? ""}
          onChange={(e) => updateEdit(filePath, pane, e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          style={{
            flex: 1,
            background: "#0a0a0a",
            color: "#d4d4d4",
            border: "none",
            outline: "none",
            resize: "none",
            padding: "8px 12px",
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontSize: 13,
            lineHeight: "20px",
            tabSize: 4,
            whiteSpace: "pre",
            overflow: "auto",
          }}
        />
      ) : (
        <div style={{ flex: 1, overflow: "auto", background: "#0a0a0a" }}>
          <pre
            style={{
              margin: 0,
              padding: "8px 0",
              fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
              fontSize: 13,
              lineHeight: "20px",
              color: "#d4d4d4",
            }}
          >
            {lines.map((line, i) => (
              <div key={i} style={{ display: "flex", minHeight: 20 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 48,
                    textAlign: "right",
                    paddingRight: 16,
                    color: "#444",
                    userSelect: "none",
                    flexShrink: 0,
                  }}
                >
                  {i + 1}
                </span>
                <span style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                  {line || " "}
                </span>
              </div>
            ))}
          </pre>
        </div>
      )}

      {writeMutation.error && (
        <div style={{ padding: "6px 12px", background: "rgba(239,68,68,0.1)", color: "#ef4444", fontSize: 12 }}>
          Save failed: {writeMutation.error.message}
        </div>
      )}
    </div>
  );
}
