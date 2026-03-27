import { useState, useRef } from "react";
import { FolderOpen, Unlink, Save, X, Edit3, FileText } from "lucide-react";
import { useWorkspaces, useWorkspaceFileContent, useWriteWorkspaceFile } from "../../api/hooks/useWorkspaces";
import { WorkspaceFilePicker } from "./WorkspaceFilePicker";

interface Props {
  /** Default workspace id (e.g. from the bot). Null/undefined = let user pick. */
  workspaceId?: string | null;
  filePath: string | null;
  /** Called with (path, workspaceId) when a file is selected. */
  onLink: (path: string, workspaceId: string) => void;
  onUnlink: () => void;
}

export function WorkspaceFilePrompt({ workspaceId, filePath, onLink, onUnlink }: Props) {
  const { data: workspaces } = useWorkspaces();
  const hasAnyWorkspace = (workspaces?.length ?? 0) > 0;

  if (filePath && workspaceId) {
    return (
      <InlineViewer
        workspaceId={workspaceId}
        filePath={filePath}
        onUnlink={onUnlink}
      />
    );
  }

  return (
    <BrowseButton
      defaultWorkspaceId={workspaceId}
      workspaces={workspaces ?? []}
      hasAnyWorkspace={hasAnyWorkspace}
      onLink={onLink}
    />
  );
}

// ---------------------------------------------------------------------------
// Browse button (when no file is linked) — always visible
// ---------------------------------------------------------------------------
interface WorkspaceSummary {
  id: string;
  name: string;
}

function BrowseButton({
  defaultWorkspaceId,
  workspaces,
  hasAnyWorkspace,
  onLink,
}: {
  defaultWorkspaceId?: string | null;
  workspaces: WorkspaceSummary[];
  hasAnyWorkspace: boolean;
  onLink: (path: string, workspaceId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState("");
  const [pickerWsId, setPickerWsId] = useState<string | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const effectiveWsId = pickerWsId ?? defaultWorkspaceId ?? workspaces[0]?.id ?? null;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={btnRef}
        onClick={() => { setOpen(!open); setSelected(""); setPickerWsId(null); }}
        style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "3px 8px", fontSize: 11, fontWeight: 600,
          border: "1px solid #333", borderRadius: 4,
          background: open ? "#1a1a1a" : "transparent",
          color: "#888", cursor: "pointer",
        }}
      >
        <FolderOpen size={11} />
        Browse Workspace File
      </button>

      {open && typeof document !== "undefined" && (() => {
        const ReactDOM = require("react-dom");
        return ReactDOM.createPortal(
          <>
            <div
              onClick={() => { setOpen(false); setSelected(""); }}
              style={{ position: "fixed", inset: 0, zIndex: 10010 }}
            />
            <div
              style={{
                position: "fixed",
                top: (btnRef.current?.getBoundingClientRect().bottom ?? 0) + 4,
                left: btnRef.current?.getBoundingClientRect().left ?? 0,
                width: 400,
                zIndex: 10011,
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                display: "flex",
                flexDirection: "column",
                padding: 12,
                gap: 10,
              }}
            >
              <div style={{ fontSize: 11, fontWeight: 600, color: "#999", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Select workspace file
              </div>

              {!hasAnyWorkspace ? (
                <div style={{ padding: "16px 8px", textAlign: "center", color: "#555", fontSize: 12 }}>
                  No workspaces available. Create a workspace first.
                </div>
              ) : (
                <>
                  {/* Workspace selector (show when multiple workspaces exist) */}
                  {workspaces.length > 1 && (
                    <select
                      value={effectiveWsId ?? ""}
                      onChange={(e) => { setPickerWsId(e.target.value); setSelected(""); }}
                      style={{
                        background: "#111",
                        border: "1px solid #333",
                        borderRadius: 4,
                        padding: "5px 8px",
                        fontSize: 11,
                        color: "#e5e5e5",
                        outline: "none",
                      }}
                    >
                      {workspaces.map((ws) => (
                        <option key={ws.id} value={ws.id}>{ws.name}</option>
                      ))}
                    </select>
                  )}

                  {effectiveWsId && (
                    <WorkspaceFilePicker
                      workspaceId={effectiveWsId}
                      value={selected}
                      onChange={setSelected}
                    />
                  )}
                </>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                <button
                  onClick={() => { setOpen(false); setSelected(""); }}
                  style={{
                    padding: "4px 12px", fontSize: 11,
                    background: "transparent", border: "1px solid #333",
                    borderRadius: 4, color: "#888", cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (selected && effectiveWsId) {
                      onLink(selected, effectiveWsId);
                      setOpen(false);
                      setSelected("");
                    }
                  }}
                  disabled={!selected}
                  style={{
                    padding: "4px 12px", fontSize: 11, fontWeight: 600,
                    background: selected ? "#22c55e" : "#333",
                    color: selected ? "#fff" : "#666",
                    border: "none", borderRadius: 4,
                    cursor: selected ? "pointer" : "not-allowed",
                  }}
                >
                  Link
                </button>
              </div>
            </div>
          </>,
          document.body
        );
      })()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline file viewer (when a file is linked)
// ---------------------------------------------------------------------------
function InlineViewer({ workspaceId, filePath, onUnlink }: { workspaceId: string; filePath: string; onUnlink: () => void }) {
  const { data, isLoading, error } = useWorkspaceFileContent(workspaceId, filePath);
  const writeMutation = useWriteWorkspaceFile(workspaceId);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");

  const handleStartEdit = () => {
    if (data?.content != null) {
      setEditContent(data.content);
      setEditing(true);
    }
  };

  const handleSave = async () => {
    try {
      await writeMutation.mutateAsync({ path: filePath, content: editContent });
      setEditing(false);
    } catch {
      // error shown via mutation state
    }
  };

  const handleCancel = () => {
    setEditing(false);
    setEditContent("");
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

  const content = data?.content ?? "";
  const lines = content.split("\n");

  return (
    <div style={{
      border: "1px solid #222",
      borderRadius: 8,
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      height: 300,
    }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "4px 12px",
        borderBottom: "1px solid #222",
        background: "#0d0d0d",
        flexShrink: 0,
      }}>
        <FileText size={12} color="#86efac" />
        <span style={{ flex: 1, fontSize: 11, color: "#86efac", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace" }}>
          {filePath}
        </span>
        {data?.size != null && (
          <span style={{ fontSize: 10, color: "#555" }}>
            {data.size > 1024 ? `${(data.size / 1024).toFixed(1)}KB` : `${data.size}B`}
          </span>
        )}
        {editing ? (
          <>
            <button
              onClick={handleSave}
              disabled={writeMutation.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                background: "#22c55e", color: "#000", border: "none",
                borderRadius: 4, padding: "3px 10px", fontSize: 11,
                cursor: "pointer", fontWeight: 600,
              }}
            >
              <Save size={11} /> {writeMutation.isPending ? "..." : "Save"}
            </button>
            <button
              onClick={handleCancel}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                background: "none", color: "#999", border: "1px solid #333",
                borderRadius: 4, padding: "3px 10px", fontSize: 11,
                cursor: "pointer",
              }}
            >
              <X size={11} /> Cancel
            </button>
          </>
        ) : (
          <button
            onClick={handleStartEdit}
            disabled={isLoading || !!error}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: "none", color: "#999", border: "1px solid #333",
              borderRadius: 4, padding: "3px 10px", fontSize: 11,
              cursor: "pointer",
            }}
          >
            <Edit3 size={11} /> Edit
          </button>
        )}
        <button
          onClick={onUnlink}
          title="Unlink workspace file"
          style={{
            display: "flex", alignItems: "center", gap: 3,
            padding: "3px 8px", fontSize: 10,
            border: "1px solid #333", borderRadius: 4,
            background: "transparent", color: "#888", cursor: "pointer",
          }}
        >
          <Unlink size={10} /> Unlink
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#666", fontSize: 12 }}>
          Loading...
        </div>
      ) : error ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#ef4444", padding: 24, fontSize: 12 }}>
          {(error as any)?.body ? JSON.parse((error as any).body)?.detail : error.message}
        </div>
      ) : editing ? (
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          autoFocus
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
          <pre style={{
            margin: 0,
            padding: "8px 0",
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontSize: 13,
            lineHeight: "20px",
            color: "#d4d4d4",
          }}>
            {lines.map((line, i) => (
              <div key={i} style={{ display: "flex", minHeight: 20 }}>
                <span style={{
                  display: "inline-block",
                  width: 48,
                  textAlign: "right",
                  paddingRight: 16,
                  color: "#444",
                  userSelect: "none",
                  flexShrink: 0,
                }}>
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
        <div style={{ padding: "6px 12px", background: "rgba(239,68,68,0.1)", color: "#ef4444", fontSize: 11 }}>
          Save failed: {writeMutation.error.message}
        </div>
      )}
    </div>
  );
}
