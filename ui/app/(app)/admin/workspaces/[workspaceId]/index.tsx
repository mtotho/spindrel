import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  ChevronLeft, Trash2, Play, Square, RefreshCw, Download,
  Plus, X, FolderOpen, ChevronRight, FileText, Folder, AlertCircle,
  Edit3, Save, FolderPlus, FilePlus,
} from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import {
  useWorkspace, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
  useStartWorkspace, useStopWorkspace, useRecreateWorkspace,
  usePullWorkspaceImage, useWorkspaceStatus, useWorkspaceLogs,
  useAddBotToWorkspace, useUpdateWorkspaceBot, useRemoveBotFromWorkspace,
  useWorkspaceFiles, useReindexWorkspace,
  useWorkspaceFileContent, useWriteWorkspaceFile, useMkdirWorkspace, useDeleteWorkspaceFile,
  useEnableEditor, useDisableEditor, useEditorStatus, createEditorSession,
} from "@/src/api/hooks/useWorkspaces";
import { useBots } from "@/src/api/hooks/useBots";
import { apiFetch } from "@/src/api/client";
import type { SharedWorkspace } from "@/src/types/api";
import {
  FormRow, TextInput, SelectInput, Toggle, Section, Row, Col,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";
import { IndexingOverview } from "./IndexingOverview";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  running: { bg: "rgba(34,197,94,0.15)", fg: "#16a34a" },
  stopped: { bg: "rgba(100,100,100,0.15)", fg: "#999" },
  creating: { bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  error: { bg: "rgba(239,68,68,0.15)", fg: "#dc2626" },
};

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.stopped;
  return (
    <span style={{
      padding: "3px 10px", borderRadius: 5, fontSize: 12, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Env var editor
// ---------------------------------------------------------------------------
function EnvEditor({ entries, onChange }: {
  entries: { key: string; value: string }[];
  onChange: (entries: { key: string; value: string }[]) => void;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map((entry, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={entry.key}
            onChange={(e) => {
              const next = [...entries];
              next[i] = { ...next[i], key: e.target.value };
              onChange(next);
            }}
            placeholder="KEY"
            style={{
              flex: 1, background: t.inputBg,
              border: `1px solid ${!entry.key ? "#7f1d1d" : t.surfaceBorder}`,
              borderRadius: 6,
              padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <span style={{ color: t.textDim }}>=</span>
          <input
            value={entry.value}
            onChange={(e) => {
              const next = [...entries];
              next[i] = { ...next[i], value: e.target.value };
              onChange(next);
            }}
            placeholder="value"
            style={{
              flex: 2, background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
              padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={() => onChange(entries.filter((_, j) => j !== i))}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: t.textDim, padding: 2, flexShrink: 0,
            }}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...entries, { key: "", value: "" }])}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          padding: "4px 10px", fontSize: 11, fontWeight: 600,
          border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
          background: "transparent", color: t.textMuted, cursor: "pointer",
          alignSelf: "flex-start",
        }}
      >
        <Plus size={12} /> Add Variable
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connected bots section
// ---------------------------------------------------------------------------
function ConnectedBots({ workspaceId, bots, isWide }: {
  workspaceId: string;
  bots: { bot_id: string; bot_name: string; role: string; cwd_override?: string | null }[];
  isWide: boolean;
}) {
  const t = useThemeTokens();
  const { data: allBots } = useBots();
  const addBot = useAddBotToWorkspace(workspaceId);
  const updateBot = useUpdateWorkspaceBot(workspaceId);
  const removeBot = useRemoveBotFromWorkspace(workspaceId);
  const [addBotId, setAddBotId] = useState("");

  const assignedIds = new Set(bots.map((b) => b.bot_id));
  const availableBots = allBots?.filter((b) => !assignedIds.has(b.id)) ?? [];

  const handleAdd = () => {
    if (!addBotId) return;
    addBot.mutate({ bot_id: addBotId, role: "member" });
    setAddBotId("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {bots.length === 0 && (
        <div style={{ color: t.textDim, fontSize: 12 }}>No bots connected.</div>
      )}
      {bots.map((b) => (
        <div key={b.bot_id} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", background: t.surface, borderRadius: 8,
          border: `1px solid ${t.surfaceRaised}`,
        }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: t.text, flex: 1,
            minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {b.bot_name || b.bot_id}
          </span>
          <select
            value={b.role}
            onChange={(e) => updateBot.mutate({ bot_id: b.bot_id, role: e.target.value })}
            style={{
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
              padding: "3px 8px", color: t.text, fontSize: 11, cursor: "pointer",
              outline: "none",
            }}
          >
            <option value="member">Member</option>
            <option value="orchestrator">Orchestrator</option>
          </select>
          <button
            onClick={() => removeBot.mutate(b.bot_id)}
            disabled={removeBot.isPending}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: t.textDim, padding: 2, flexShrink: 0,
            }}
          >
            <X size={14} />
          </button>
        </div>
      ))}

      {/* Add bot */}
      {availableBots.length > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
          <select
            value={addBotId}
            onChange={(e) => setAddBotId(e.target.value)}
            style={{
              flex: 1, background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
              padding: "5px 8px", color: t.text, fontSize: 12, cursor: "pointer",
              outline: "none",
            }}
          >
            <option value="">Select bot...</option>
            {availableBots.map((b) => (
              <option key={b.id} value={b.id}>{b.name} ({b.id})</option>
            ))}
          </select>
          <button
            onClick={handleAdd}
            disabled={!addBotId || addBot.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 12px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: addBotId ? t.accent : t.surfaceBorder,
              color: addBotId ? "#fff" : t.textDim,
              cursor: addBotId ? "pointer" : "not-allowed",
              flexShrink: 0,
            }}
          >
            <Plus size={13} /> Add
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Container controls
// ---------------------------------------------------------------------------
function ContainerControls({ workspaceId, status }: { workspaceId: string; status: string }) {
  const t = useThemeTokens();
  const startMut = useStartWorkspace(workspaceId);
  const stopMut = useStopWorkspace(workspaceId);
  const recreateMut = useRecreateWorkspace(workspaceId);
  const pullMut = usePullWorkspaceImage(workspaceId);
  const { data: logsData, refetch: refetchLogs } = useWorkspaceLogs(
    status === "running" ? workspaceId : undefined
  );
  const [showLogs, setShowLogs] = useState(false);
  const [pullResult, setPullResult] = useState<string | null>(null);

  const busy = startMut.isPending || stopMut.isPending || recreateMut.isPending;
  const isRunning = status === "running";

  const handlePull = () => {
    setPullResult(null);
    pullMut.mutate(undefined, {
      onSuccess: (r) => setPullResult(r.output || "Image pulled successfully"),
      onError: (e) => setPullResult((e as any)?.message || "Pull failed"),
    });
  };

  const btnStyle = (active: boolean): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 6,
    padding: "6px 14px", fontSize: 12, fontWeight: 600,
    border: `1px solid ${active ? t.surfaceBorder : t.surfaceOverlay}`, borderRadius: 6,
    background: "transparent",
    color: active ? t.text : t.textDim,
    cursor: active ? "pointer" : "not-allowed",
    opacity: active ? 1 : 0.5,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button
          onClick={() => startMut.mutate()}
          disabled={busy || isRunning}
          style={btnStyle(!isRunning && !busy)}
        >
          <Play size={13} />
          {startMut.isPending ? "Starting..." : "Start"}
        </button>
        <button
          onClick={() => stopMut.mutate()}
          disabled={busy || !isRunning}
          style={btnStyle(isRunning && !busy)}
        >
          <Square size={13} />
          {stopMut.isPending ? "Stopping..." : "Stop"}
        </button>
        <button
          onClick={() => {
            if (confirm("Recreate this container? Data in /workspace persists.")) {
              recreateMut.mutate();
            }
          }}
          disabled={busy}
          style={btnStyle(!busy)}
        >
          <RefreshCw size={13} />
          {recreateMut.isPending ? "Recreating..." : "Recreate"}
        </button>
        <button
          onClick={handlePull}
          disabled={pullMut.isPending}
          style={btnStyle(!pullMut.isPending)}
        >
          <Download size={13} />
          {pullMut.isPending ? "Pulling..." : "Pull Image"}
        </button>
      </div>

      {pullResult && (
        <div style={{
          padding: "6px 12px", fontSize: 11, borderRadius: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceOverlay}`,
          color: t.textMuted, fontFamily: "monospace", whiteSpace: "pre-wrap",
          maxHeight: 120, overflowY: "auto",
        }}>
          {pullResult}
        </div>
      )}

      {/* Logs toggle */}
      {isRunning && (
        <div>
          <button
            onClick={() => { setShowLogs(!showLogs); if (!showLogs) refetchLogs(); }}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: "none", border: "none", cursor: "pointer",
              color: t.textMuted, fontSize: 12, padding: 0,
            }}
          >
            <FileText size={12} />
            {showLogs ? "Hide Logs" : "Show Logs"}
          </button>
          {showLogs && (
            <div style={{
              marginTop: 8, padding: 12, background: t.surface, borderRadius: 8,
              border: `1px solid ${t.surfaceRaised}`, maxHeight: 300, overflowY: "auto",
            }}>
              <pre style={{
                color: t.textMuted, fontSize: 11, fontFamily: "monospace",
                whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.5,
              }}>
                {logsData?.logs || "No logs available"}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editor section (code-server)
// ---------------------------------------------------------------------------
function EditorSection({ workspace }: { workspace: SharedWorkspace }) {
  const t = useThemeTokens();
  const enableMut = useEnableEditor(workspace.id);
  const disableMut = useDisableEditor(workspace.id);
  const { data: editorStatus } = useEditorStatus(workspace.id);
  const [opening, setOpening] = useState(false);

  const isRunning = workspace.status === "running";
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
      if (!editorEnabled) {
        await enableMut.mutateAsync();
      }
      await createEditorSession(workspace.id);
      const { useAuthStore } = await import("@/src/stores/auth");
      const { serverUrl } = useAuthStore.getState();
      const url = `${serverUrl}/api/v1/workspaces/${workspace.id}/editor/`;
      window.open(url, `editor-${workspace.id}`);
    } catch (err) {
      console.error("Failed to open editor:", err);
    } finally {
      setOpening(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Toggle
            value={editorEnabled}
            onChange={handleToggle}
            label={editorEnabled ? "Enabled" : "Disabled"}
          />
          {editorEnabled && (
            <span style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 4,
              background: editorRunning ? "rgba(34,197,94,0.15)" : "rgba(100,100,100,0.15)",
              color: editorRunning ? "#16a34a" : "#999",
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
              display: "flex", alignItems: "center", gap: 6,
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
        <div style={{ fontSize: 11, color: "#d97706" }}>
          Start the workspace to use the editor.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File browser with view/edit/create/delete
// ---------------------------------------------------------------------------
function FileBrowser({ workspaceId }: { workspaceId: string }) {
  const t = useThemeTokens();
  const [path, setPath] = useState("/");
  const [viewingFile, setViewingFile] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [newName, setNewName] = useState("");

  const { data, isLoading, refetch } = useWorkspaceFiles(workspaceId, path);
  const { data: fileData, isLoading: fileLoading, error: fileError } = useWorkspaceFileContent(
    workspaceId, viewingFile
  );
  const writeMut = useWriteWorkspaceFile(workspaceId);
  const mkdirMut = useMkdirWorkspace(workspaceId);
  const deleteMut = useDeleteWorkspaceFile(workspaceId);

  const navigateTo = (entryPath: string) => {
    setViewingFile(null);
    setEditing(false);
    setPath(entryPath);
  };
  const navigateUp = () => {
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    navigateTo(parent);
  };

  const handleSaveFile = () => {
    if (!viewingFile) return;
    writeMut.mutate({ path: viewingFile, content: editContent }, {
      onSuccess: () => { setEditing(false); refetch(); },
    });
  };

  const handleCreate = () => {
    if (!newName.trim()) return;
    const newPath = path === "/" ? newName.trim() : `${path.replace(/^\//, "")}/${newName.trim()}`;
    if (creating === "folder") {
      mkdirMut.mutate(newPath, { onSuccess: () => { setCreating(null); setNewName(""); refetch(); } });
    } else {
      writeMut.mutate({ path: newPath, content: "" }, {
        onSuccess: () => { setCreating(null); setNewName(""); refetch(); },
      });
    }
  };

  const handleDelete = (entryPath: string, entryName: string, isDir: boolean) => {
    if (!confirm(`Delete ${isDir ? "directory" : "file"} "${entryName}"?`)) return;
    deleteMut.mutate(entryPath, {
      onSuccess: () => {
        if (viewingFile === entryPath) { setViewingFile(null); setEditing(false); }
        refetch();
      },
    });
  };

  const formatSize = (size: number | null | undefined) => {
    if (size == null) return "";
    if (size > 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)}M`;
    if (size > 1024) return `${(size / 1024).toFixed(1)}K`;
    return `${size}B`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Breadcrumb + toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 0, fontSize: 12, flexWrap: "wrap" }}>
        <button
          onClick={() => navigateTo("/")}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: path === "/" ? t.text : "#2563eb", fontSize: 12, padding: 0,
            fontFamily: "monospace",
          }}
        >
          /workspace
        </button>
        {path !== "/" && (() => {
          const segments = path.replace(/^\//, "").split("/").filter(Boolean);
          return segments.map((seg, i) => {
            const segPath = "/" + segments.slice(0, i + 1).join("/");
            const isLast = i === segments.length - 1;
            return (
              <span key={segPath} style={{ display: "inline-flex", alignItems: "center" }}>
                <span style={{ color: t.textDim, margin: "0 1px" }}>/</span>
                <button
                  onClick={() => navigateTo(segPath)}
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: isLast ? t.text : "#2563eb", fontSize: 12, padding: 0,
                    fontFamily: "monospace",
                  }}
                >
                  {seg}
                </button>
              </span>
            );
          });
        })()}
        <div style={{ flex: 1 }} />
        <button
          onClick={() => { setCreating("file"); setNewName(""); }}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <FilePlus size={11} /> New File
        </button>
        <button
          onClick={() => { setCreating("folder"); setNewName(""); }}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <FolderPlus size={11} /> New Folder
        </button>
        <button
          onClick={() => refetch()}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <RefreshCw size={10} />
        </button>
      </div>

      {/* Create inline form */}
      {creating && (
        <div style={{
          display: "flex", gap: 6, alignItems: "center",
          padding: "6px 10px", background: t.inputBg, borderRadius: 6, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <span style={{ fontSize: 11, color: t.textMuted }}>
            {creating === "folder" ? "Folder:" : "File:"}
          </span>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") setCreating(null); }}
            placeholder={creating === "folder" ? "folder-name" : "filename.txt"}
            style={{
              flex: 1, background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
              padding: "3px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={handleCreate}
            disabled={!newName.trim() || mkdirMut.isPending || writeMut.isPending}
            style={{
              padding: "3px 10px", fontSize: 11, fontWeight: 600,
              background: newName.trim() ? t.accent : t.surfaceBorder,
              color: newName.trim() ? "#fff" : t.textDim,
              border: "none", borderRadius: 4, cursor: newName.trim() ? "pointer" : "not-allowed",
            }}
          >
            Create
          </button>
          <button
            onClick={() => setCreating(null)}
            style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Entries */}
      {isLoading ? (
        <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Loading...</div>
      ) : (
        <div style={{
          background: t.surface, borderRadius: 8, border: `1px solid ${t.surfaceRaised}`,
          overflow: "hidden",
        }}>
          {(!data?.entries || data.entries.length === 0) && (
            <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Empty directory</div>
          )}
          {data?.entries?.map((entry) => (
            <div
              key={entry.path}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px",
                background: viewingFile === entry.path ? "rgba(59,130,246,0.08)" : "transparent",
                borderBottom: `1px solid ${t.inputBg}`,
              }}
            >
              <button
                onClick={() => {
                  if (entry.is_dir) {
                    navigateTo(entry.path);
                  } else {
                    setViewingFile(entry.path);
                    setEditing(false);
                  }
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 8, flex: 1,
                  background: "none", border: "none", cursor: "pointer",
                  textAlign: "left", padding: 0,
                }}
              >
                {entry.is_dir ? (
                  <Folder size={13} color="#2563eb" />
                ) : (
                  <FileText size={13} color={t.textDim} />
                )}
                <span style={{
                  flex: 1, fontSize: 12, color: entry.is_dir ? t.text : t.textMuted,
                  fontFamily: "monospace",
                }}>
                  {entry.name}
                </span>
                {!entry.is_dir && entry.size != null && (
                  <span style={{ fontSize: 10, color: t.textDim }}>{formatSize(entry.size)}</span>
                )}
                {entry.is_dir && <ChevronRight size={12} color={t.textDim} />}
              </button>
              <button
                onClick={() => handleDelete(entry.path, entry.name, entry.is_dir)}
                disabled={deleteMut.isPending}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: t.surfaceBorder, padding: 2, flexShrink: 0,
                }}
                title="Delete"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* File viewer/editor panel */}
      {viewingFile && (
        <div style={{
          background: t.surface, borderRadius: 8, border: `1px solid ${t.surfaceRaised}`,
          overflow: "hidden",
        }}>
          {/* File header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 12px", borderBottom: `1px solid ${t.surfaceRaised}`,
            background: t.inputBg,
          }}>
            <FileText size={13} color="#2563eb" />
            <span style={{ flex: 1, fontSize: 12, color: t.text, fontFamily: "monospace" }}>
              {viewingFile}
            </span>
            {fileData && !editing && (
              <button
                onClick={() => { setEditing(true); setEditContent(fileData.content); }}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "3px 10px", fontSize: 11, fontWeight: 600,
                  background: "transparent", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                  color: t.textMuted, cursor: "pointer",
                }}
              >
                <Edit3 size={11} /> Edit
              </button>
            )}
            {editing && (
              <>
                <button
                  onClick={handleSaveFile}
                  disabled={writeMut.isPending}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "3px 10px", fontSize: 11, fontWeight: 600,
                    background: t.accent, border: "none", borderRadius: 4,
                    color: "#fff", cursor: "pointer",
                  }}
                >
                  <Save size={11} /> {writeMut.isPending ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setEditing(false)}
                  style={{
                    padding: "3px 10px", fontSize: 11,
                    background: "transparent", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                    color: t.textMuted, cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </>
            )}
            <button
              onClick={() => { setViewingFile(null); setEditing(false); }}
              style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 2 }}
            >
              <X size={14} />
            </button>
          </div>

          {/* File content */}
          <div style={{ padding: 12, maxHeight: 400, overflowY: "auto" }}>
            {fileLoading && (
              <div style={{ color: t.textDim, fontSize: 12 }}>Loading file...</div>
            )}
            {fileError && (
              <div style={{ color: "#dc2626", fontSize: 12 }}>
                {(fileError as any)?.message || "Failed to load file"}
              </div>
            )}
            {fileData && !editing && (
              <pre style={{
                color: t.text, fontSize: 12, fontFamily: "monospace",
                whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.5,
                wordBreak: "break-all",
              }}>
                {fileData.content || <span style={{ color: t.textDim }}>(empty file)</span>}
              </pre>
            )}
            {editing && (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                style={{
                  width: "100%", minHeight: 200, background: "#0d0d0d",
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                  padding: 10, color: t.text, fontSize: 12, fontFamily: "monospace",
                  lineHeight: 1.5, resize: "vertical", outline: "none",
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function WorkspaceDetailScreen() {
  const t = useThemeTokens();
  const { workspaceId } = useLocalSearchParams<{ workspaceId: string }>();
  const isNew = workspaceId === "new";
  const goBack = useGoBack("/admin/workspaces");
  const qc = useQueryClient();

  const { data: workspace, isLoading } = useWorkspace(isNew ? undefined : workspaceId);
  const { data: liveStatus } = useWorkspaceStatus(
    !isNew && workspace ? workspaceId : undefined
  );
  const createMut = useCreateWorkspace();
  const updateMut = useUpdateWorkspace(workspaceId!);
  const deleteMut = useDeleteWorkspace();
  const reindexMut = useReindexWorkspace(workspaceId!);

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [image, setImage] = useState("agent-workspace:latest");
  const [network, setNetwork] = useState("none");
  const [env, setEnv] = useState<{ key: string; value: string }[]>([]);
  const [ports, setPorts] = useState<{ host: string; container: string }[]>([]);
  const [mounts, setMounts] = useState<{ host_path: string; container_path: string; mode: string }[]>([]);
  const [cpus, setCpus] = useState("");
  const [memoryLimit, setMemoryLimit] = useState("");
  const [dockerUser, setDockerUser] = useState("");
  const [readOnlyRoot, setReadOnlyRoot] = useState(false);
  const [startupScript, setStartupScript] = useState("/workspace/startup.sh");
  const [skillsEnabled, setSkillsEnabled] = useState(true);
  const [basePromptEnabled, setBasePromptEnabled] = useState(true);
  const [initialized, setInitialized] = useState(isNew);

  if (workspace && !initialized) {
    setName(workspace.name || "");
    setDescription(workspace.description || "");
    setImage(workspace.image || "agent-workspace:latest");
    setNetwork(workspace.network || "none");
    setEnv(Object.entries(workspace.env || {}).map(([k, v]) => ({ key: k, value: v as string })));
    setPorts((workspace.ports || []).map((p: any) =>
      typeof p === "string"
        ? { host: p.split(":")[0] || "", container: p.split(":")[1] || "" }
        : { host: String(p.host || ""), container: String(p.container || "") }
    ));
    setMounts((workspace.mounts || []).map((m: any) => ({
      host_path: m.host_path || "", container_path: m.container_path || "", mode: m.mode || "rw",
    })));
    setCpus(workspace.cpus ? String(workspace.cpus) : "");
    setMemoryLimit(workspace.memory_limit || "");
    setDockerUser(workspace.docker_user || "");
    setReadOnlyRoot(workspace.read_only_root || false);
    setStartupScript(workspace.startup_script ?? "/workspace/startup.sh");
    setSkillsEnabled(workspace.workspace_skills_enabled ?? true);
    setBasePromptEnabled(workspace.workspace_base_prompt_enabled ?? true);
    setInitialized(true);
  }

  const currentStatus = liveStatus?.status || workspace?.status || "stopped";

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!name.trim()) return;
      const validPorts = ports.filter((p) => p.host && p.container);
      const validMounts = mounts.filter((m) => m.host_path && m.container_path);
      const envDict = Object.fromEntries(env.filter((e) => e.key).map((e) => [e.key, e.value]));
      await createMut.mutateAsync({
        name: name.trim(),
        description: description || undefined,
        image: image || undefined,
        network: network || undefined,
        env: Object.keys(envDict).length ? envDict : undefined,
        ports: validPorts.length ? validPorts : undefined,
        mounts: validMounts.length ? validMounts : undefined,
        cpus: cpus ? parseFloat(cpus) : undefined,
        memory_limit: memoryLimit || undefined,
        docker_user: dockerUser || undefined,
        read_only_root: readOnlyRoot,
        startup_script: startupScript || undefined,
        workspace_skills_enabled: skillsEnabled,
        workspace_base_prompt_enabled: basePromptEnabled,
      });
      goBack();
    } else {
      const validPorts = ports.filter((p) => p.host && p.container);
      const validMounts = mounts.filter((m) => m.host_path && m.container_path);
      const envDict = Object.fromEntries(env.filter((e) => e.key).map((e) => [e.key, e.value]));
      await updateMut.mutateAsync({
        name: name.trim() || undefined,
        description,
        image: image || undefined,
        network: network || undefined,
        env: envDict,
        ports: validPorts.length ? validPorts : undefined,
        mounts: validMounts.length ? validMounts : undefined,
        cpus: cpus ? parseFloat(cpus) : undefined,
        memory_limit: memoryLimit || undefined,
        docker_user: dockerUser || undefined,
        read_only_root: readOnlyRoot,
        startup_script: startupScript || undefined,
        workspace_skills_enabled: skillsEnabled,
        workspace_base_prompt_enabled: basePromptEnabled,
      });
      // Update snapshot so dirty tracking resets
      savedSnapshot.current = currentSnapshot;
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2000);
    }
  }, [isNew, name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!workspaceId || !confirm("Delete this workspace? The container and data will be removed.")) return;
    await deleteMut.mutateAsync(workspaceId);
    goBack();
  }, [workspaceId, deleteMut, goBack]);

  // -- Dirty tracking: compare current form state to last-saved snapshot --
  const savedSnapshot = useRef<string>("");
  const currentSnapshot = useMemo(() =>
    JSON.stringify({ name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled }),
    [name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled],
  );
  // Set snapshot after initialization from server data
  useEffect(() => {
    if (initialized && !savedSnapshot.current) {
      savedSnapshot.current = currentSnapshot;
    }
  }, [initialized, currentSnapshot]);

  const isDirty = isNew || (initialized && currentSnapshot !== savedSnapshot.current);

  // -- Save success flash --
  const [justSaved, setJustSaved] = useState(false);

  // -- Validation warnings --
  const hasEmptyEnvKeys = env.some((e) => !e.key);
  const hasIncompletePort = ports.some((p) => (!p.host && p.container) || (p.host && !p.container));
  const hasIncompleteMount = mounts.some((m) => (!m.host_path && m.container_path) || (m.host_path && !m.container_path));
  const hasWarnings = hasEmptyEnvKeys || hasIncompletePort || hasIncompleteMount;

  // -- Warn on navigate away with unsaved changes --
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = !!name.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`, gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ChevronLeft size={22} color={t.textMuted} />
        </button>
        <span style={{ color: t.text, fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New Workspace" : "Edit Workspace"}
        </span>
        {!isNew && isWide && (
          <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>
            {workspaceId?.slice(0, 8)}
          </span>
        )}
        {!isNew && <StatusBadge status={currentStatus} />}
        <div style={{ flex: 1 }} />
        {!isNew && (
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            title="Delete"
            style={{
              display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: "1px solid rgba(239,68,68,0.25)", borderRadius: 6,
              background: "transparent", color: "#dc2626", cursor: "pointer", flexShrink: 0,
            }}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
        )}
        {/* Unsaved indicator */}
        {isDirty && !isNew && !justSaved && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: "#d97706",
            flexShrink: 0, whiteSpace: "nowrap",
          }}>
            Unsaved changes
          </span>
        )}
        {justSaved && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: "#16a34a",
            flexShrink: 0,
          }}>
            Saved
          </span>
        )}
        <button
          onClick={handleSave}
          disabled={isSaving || !canSave}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: isDirty && canSave ? `2px solid ${t.accent}` : "none",
            borderRadius: 6, flexShrink: 0,
            background: !canSave ? t.surfaceBorder : isDirty ? t.accent : t.accentMuted,
            color: !canSave ? t.textDim : isDirty ? "#fff" : t.accent,
            cursor: !canSave ? "not-allowed" : "pointer",
            transition: "all 0.2s",
          }}
        >
          {isSaving ? "Saving..." : "Save"}
        </button>
      </div>

      {/* Validation warnings bar */}
      {hasWarnings && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "6px 20px", background: "rgba(251,191,36,0.08)",
          borderBottom: "1px solid rgba(251,191,36,0.15)",
          fontSize: 12, color: "#d97706",
        }}>
          <AlertCircle size={14} />
          <span>
            {hasEmptyEnvKeys && "Some env vars have empty keys. "}
            {hasIncompletePort && "Some port mappings are incomplete. "}
            {hasIncompleteMount && "Some mounts are incomplete. "}
            Incomplete entries will be ignored on save.
          </span>
        </div>
      )}

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: "rgba(239,68,68,0.12)", color: "#dc2626", fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        paddingVertical: isWide ? 20 : 12,
        paddingHorizontal: isWide ? 24 : 12,
        maxWidth: 800,
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {/* Identity */}
          <Section title="Identity">
            <FormRow label="Name" description="Unique workspace name">
              <TextInput value={name} onChangeText={setName} placeholder="e.g. my-workspace" />
            </FormRow>
            <FormRow label="Description">
              <TextInput value={description} onChangeText={setDescription} placeholder="Optional description" />
            </FormRow>
          </Section>

          {/* Docker Config */}
          <Section title="Docker Configuration">
            <FormRow label="Image" description="Docker image for the workspace container">
              <TextInput value={image} onChangeText={setImage} placeholder="agent-workspace:latest" />
            </FormRow>
            <Row>
              <Col>
                <FormRow label="Network">
                  <SelectInput
                    value={network}
                    onChange={setNetwork}
                    options={[
                      { label: "None", value: "none" },
                      { label: "Bridge", value: "bridge" },
                      { label: "Host", value: "host" },
                    ]}
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Docker User" description="Run-as user inside container">
                  <TextInput value={dockerUser} onChangeText={setDockerUser} placeholder="Default (root)" />
                </FormRow>
              </Col>
            </Row>
            <FormRow label="Startup Script" description="Script path executed on every container start/recreate. Leave empty to disable.">
              <TextInput value={startupScript} onChangeText={setStartupScript} placeholder="/workspace/startup.sh" />
            </FormRow>
          </Section>

          {/* Resources */}
          <Section title="Resources">
            <Row>
              <Col>
                <FormRow label="CPUs" description="CPU limit (e.g. 2.0)">
                  <TextInput value={cpus} onChangeText={setCpus} placeholder="No limit" type="number" />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Memory Limit" description="e.g. 2g, 512m">
                  <TextInput value={memoryLimit} onChangeText={setMemoryLimit} placeholder="No limit" />
                </FormRow>
              </Col>
            </Row>
            <Toggle
              value={readOnlyRoot}
              onChange={setReadOnlyRoot}
              label="Read-only root filesystem"
              description="/workspace is always writable. Other paths become read-only."
            />
          </Section>

          {/* Environment */}
          <Section title="Environment Variables" description="Injected into the container. AGENT_SERVER_URL and AGENT_SERVER_API_KEY are auto-injected.">
            <EnvEditor entries={env} onChange={setEnv} />
          </Section>

          {/* Port Mappings */}
          <Section title="Port Mappings" description="Map host ports to container ports">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {ports.map((p, i) => (
                <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input
                    value={p.host}
                    onChange={(e) => {
                      const next = [...ports];
                      next[i] = { ...next[i], host: e.target.value };
                      setPorts(next);
                    }}
                    placeholder="Host port"
                    style={{
                      flex: 1, background: t.inputBg,
                      border: `1px solid ${!p.host && p.container ? "#7f1d1d" : t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <span style={{ color: t.textDim }}>:</span>
                  <input
                    value={p.container}
                    onChange={(e) => {
                      const next = [...ports];
                      next[i] = { ...next[i], container: e.target.value };
                      setPorts(next);
                    }}
                    placeholder="Container port"
                    style={{
                      flex: 1, background: t.inputBg,
                      border: `1px solid ${p.host && !p.container ? "#7f1d1d" : t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <button
                    onClick={() => setPorts(ports.filter((_, j) => j !== i))}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: t.textDim, padding: 2, flexShrink: 0,
                    }}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setPorts([...ports, { host: "", container: "" }])}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 10px", fontSize: 11, fontWeight: 600,
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                  background: "transparent", color: t.textMuted, cursor: "pointer",
                  alignSelf: "flex-start",
                }}
              >
                <Plus size={12} /> Add Port
              </button>
            </div>
          </Section>

          {/* Volume Mounts */}
          <Section title="Extra Mounts" description="/workspace is always mounted. Add additional host paths here.">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {mounts.map((m, i) => (
                <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input
                    value={m.host_path}
                    onChange={(e) => {
                      const next = [...mounts];
                      next[i] = { ...next[i], host_path: e.target.value };
                      setMounts(next);
                    }}
                    placeholder="Host path"
                    style={{
                      flex: 2, background: t.inputBg,
                      border: `1px solid ${!m.host_path && m.container_path ? "#7f1d1d" : t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <span style={{ color: t.textDim }}>→</span>
                  <input
                    value={m.container_path}
                    onChange={(e) => {
                      const next = [...mounts];
                      next[i] = { ...next[i], container_path: e.target.value };
                      setMounts(next);
                    }}
                    placeholder="Container path"
                    style={{
                      flex: 2, background: t.inputBg,
                      border: `1px solid ${m.host_path && !m.container_path ? "#7f1d1d" : t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <select
                    value={m.mode}
                    onChange={(e) => {
                      const next = [...mounts];
                      next[i] = { ...next[i], mode: e.target.value };
                      setMounts(next);
                    }}
                    style={{
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                      padding: "3px 6px", color: t.text, fontSize: 11, cursor: "pointer",
                      outline: "none", flexShrink: 0,
                    }}
                  >
                    <option value="rw">rw</option>
                    <option value="ro">ro</option>
                  </select>
                  <button
                    onClick={() => setMounts(mounts.filter((_, j) => j !== i))}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: t.textDim, padding: 2, flexShrink: 0,
                    }}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setMounts([...mounts, { host_path: "", container_path: "", mode: "rw" }])}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 10px", fontSize: 11, fontWeight: 600,
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                  background: "transparent", color: t.textMuted, cursor: "pointer",
                  alignSelf: "flex-start",
                }}
              >
                <Plus size={12} /> Add Mount
              </button>
            </div>
          </Section>

          {/* Workspace Skills */}
          <Section title="Workspace Skills" description="Auto-discover skill .md files from workspace filesystem and inject into bot context.">
            <FormRow label="Enable workspace skills injection">
              <Toggle value={skillsEnabled} onChange={setSkillsEnabled} />
            </FormRow>
            <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>Directory conventions:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span><code style={{ color: "#2563eb" }}>common/skills/pinned/*.md</code> — injected into every request</span>
                <span><code style={{ color: "#2563eb" }}>common/skills/rag/*.md</code> — retrieved by similarity</span>
                <span><code style={{ color: "#2563eb" }}>common/skills/on-demand/*.md</code> — available via tool call</span>
                <span><code style={{ color: "#2563eb" }}>common/skills/*.md</code> — top-level defaults to pinned</span>
                <span style={{ marginTop: 4 }}><code style={{ color: "#d97706" }}>bots/&lt;bot-id&gt;/skills/...</code> — same structure, scoped to specific bot</span>
              </div>
            </div>
            {!isNew && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                <button
                  onClick={async () => {
                    try {
                      const data = await apiFetch<{ embedded?: number; unchanged?: number; errors?: number }>(
                        `/api/v1/workspaces/${workspaceId}/reindex-skills`,
                        { method: "POST" },
                      );
                      alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                    } catch (e) {
                      alert("Failed to reindex skills");
                    }
                  }}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "5px 12px", fontSize: 11, fontWeight: 600,
                    border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                    background: "transparent", color: t.textMuted, cursor: "pointer",
                  }}
                >
                  <RefreshCw size={11} /> Reindex Skills
                </button>
              </div>
            )}
          </Section>

          {/* Workspace Base Prompt */}
          <Section title="Workspace Base Prompt" description="Override the global base prompt with a workspace-level prompt file.">
            <FormRow label="Enable workspace base prompt override">
              <Toggle value={basePromptEnabled} onChange={setBasePromptEnabled} />
            </FormRow>
            <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>File conventions:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span><code style={{ color: "#2563eb" }}>common/prompts/base.md</code> — replaces global base prompt for all workspace bots</span>
                <span><code style={{ color: "#d97706" }}>bots/&lt;bot-id&gt;/prompts/base.md</code> — concatenated after common, resolved per bot at runtime</span>
              </div>
            </div>
          </Section>

          {/* Workspace Persona */}
          <Section title="Workspace Persona" description="Override the DB persona with a workspace file. No toggle needed — file presence opts in.">
            <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>File convention:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span><code style={{ color: "#d97706" }}>bots/&lt;bot-id&gt;/persona.md</code> — overrides DB persona for that bot</span>
              </div>
            </div>
          </Section>

          {/* Code Editor */}
          {!isNew && workspace && (
            <Section title="Code Editor" description="Run VS Code (code-server) inside the workspace container. Enabling requires a container restart to map the editor port.">
              <EditorSection workspace={workspace} />
            </Section>
          )}

          {/* Container controls (only for existing workspaces) */}
          {!isNew && (
            <Section title="Container Controls">
              <ContainerControls workspaceId={workspaceId!} status={currentStatus} />
            </Section>
          )}

          {/* Connected bots (only for existing workspaces) */}
          {!isNew && workspace && (
            <Section
              title="Connected Bots"
              description="Bots that share this workspace. Orchestrators see all files; members are scoped to /workspace/bots/<bot_id>/."
            >
              <ConnectedBots
                workspaceId={workspaceId!}
                bots={workspace.bots}
                isWide={isWide}
              />
            </Section>
          )}

          {/* Indexing overview (all bots, only for existing workspaces) */}
          {!isNew && workspace && (
            <Section
              title="Indexing Overview"
              description="Resolved indexing configuration for each bot. Overridden values are highlighted."
            >
              <IndexingOverview workspaceId={workspaceId!} />
            </Section>
          )}

          {/* File browser (only for running workspaces) */}
          {!isNew && currentStatus === "running" && (
            <Section
              title="File Browser"
              action={
                <button
                  onClick={() => reindexMut.mutate()}
                  disabled={reindexMut.isPending}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "4px 10px", fontSize: 11, fontWeight: 600,
                    border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                    background: "transparent", color: t.textMuted, cursor: "pointer",
                  }}
                >
                  <RefreshCw size={11} />
                  {reindexMut.isPending ? "Reindexing..." : "Reindex"}
                </button>
              }
            >
              <FileBrowser workspaceId={workspaceId!} />
            </Section>
          )}

          {/* Info (existing workspace) */}
          {!isNew && workspace && (
            <Section title="Info">
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>ID</span>
                  <span style={{ color: t.text, fontFamily: "monospace" }}>{workspace.id}</span>
                </div>
                {workspace.container_id && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>Container</span>
                    <span style={{ color: t.textMuted, fontFamily: "monospace" }}>
                      {workspace.container_name || workspace.container_id.slice(0, 12)}
                    </span>
                  </div>
                )}
                {workspace.image_id && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>Image ID</span>
                    <span style={{ color: t.textMuted, fontFamily: "monospace" }}>{workspace.image_id.slice(0, 16)}</span>
                  </div>
                )}
                {workspace.last_started_at && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>Last Started</span>
                    <span style={{ color: t.textMuted }}>
                      {new Date(workspace.last_started_at).toLocaleString()}
                    </span>
                  </div>
                )}
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Created</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(workspace.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Updated</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(workspace.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
              </div>
            </Section>
          )}
        </div>
      </ScrollView>
    </View>
  );
}
