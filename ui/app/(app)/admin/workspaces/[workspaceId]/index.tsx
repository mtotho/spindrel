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
} from "@/src/api/hooks/useWorkspaces";
import { useBots } from "@/src/api/hooks/useBots";
import {
  FormRow, TextInput, SelectInput, Toggle, Section, Row, Col,
} from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  running: { bg: "rgba(34,197,94,0.15)", fg: "#86efac" },
  stopped: { bg: "rgba(100,100,100,0.15)", fg: "#999" },
  creating: { bg: "rgba(59,130,246,0.15)", fg: "#93c5fd" },
  error: { bg: "rgba(239,68,68,0.15)", fg: "#fca5a5" },
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
              flex: 1, background: "#111",
              border: `1px solid ${!entry.key ? "#7f1d1d" : "#333"}`,
              borderRadius: 6,
              padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <span style={{ color: "#555" }}>=</span>
          <input
            value={entry.value}
            onChange={(e) => {
              const next = [...entries];
              next[i] = { ...next[i], value: e.target.value };
              onChange(next);
            }}
            placeholder="value"
            style={{
              flex: 2, background: "#111", border: "1px solid #333", borderRadius: 6,
              padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={() => onChange(entries.filter((_, j) => j !== i))}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "#666", padding: 2, flexShrink: 0,
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
          border: "1px solid #333", borderRadius: 5,
          background: "transparent", color: "#999", cursor: "pointer",
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
        <div style={{ color: "#555", fontSize: 12 }}>No bots connected.</div>
      )}
      {bots.map((b) => (
        <div key={b.bot_id} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", background: "#0d0d0d", borderRadius: 8,
          border: "1px solid #1a1a1a",
        }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: "#e5e5e5", flex: 1,
            minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {b.bot_name || b.bot_id}
          </span>
          <select
            value={b.role}
            onChange={(e) => updateBot.mutate({ bot_id: b.bot_id, role: e.target.value })}
            style={{
              background: "#111", border: "1px solid #333", borderRadius: 5,
              padding: "3px 8px", color: "#ccc", fontSize: 11, cursor: "pointer",
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
              color: "#666", padding: 2, flexShrink: 0,
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
              flex: 1, background: "#111", border: "1px solid #333", borderRadius: 6,
              padding: "5px 8px", color: "#ccc", fontSize: 12, cursor: "pointer",
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
              background: addBotId ? "#3b82f6" : "#333",
              color: addBotId ? "#fff" : "#666",
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
    border: `1px solid ${active ? "#333" : "#222"}`, borderRadius: 6,
    background: "transparent",
    color: active ? "#ccc" : "#555",
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
          background: "#111", border: "1px solid #222",
          color: "#999", fontFamily: "monospace", whiteSpace: "pre-wrap",
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
              color: "#999", fontSize: 12, padding: 0,
            }}
          >
            <FileText size={12} />
            {showLogs ? "Hide Logs" : "Show Logs"}
          </button>
          {showLogs && (
            <div style={{
              marginTop: 8, padding: 12, background: "#0a0a0a", borderRadius: 8,
              border: "1px solid #1a1a1a", maxHeight: 300, overflowY: "auto",
            }}>
              <pre style={{
                color: "#999", fontSize: 11, fontFamily: "monospace",
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
// File browser with view/edit/create/delete
// ---------------------------------------------------------------------------
function FileBrowser({ workspaceId }: { workspaceId: string }) {
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
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, flexWrap: "wrap" }}>
        <button
          onClick={() => navigateTo("/")}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "#93c5fd", fontSize: 12, padding: 0,
          }}
        >
          /workspace
        </button>
        {path !== "/" && (
          <>
            <span style={{ color: "#555" }}>/</span>
            <span style={{ color: "#999", fontFamily: "monospace" }}>
              {path.replace(/^\//, "")}
            </span>
            <button
              onClick={navigateUp}
              style={{
                background: "none", border: "1px solid #333", borderRadius: 4,
                cursor: "pointer", color: "#999", fontSize: 10, padding: "1px 6px",
                marginLeft: 4,
              }}
            >
              Up
            </button>
          </>
        )}
        <div style={{ flex: 1 }} />
        <button
          onClick={() => { setCreating("file"); setNewName(""); }}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: "1px solid #333", borderRadius: 4,
            cursor: "pointer", color: "#999", fontSize: 10, padding: "2px 8px",
          }}
        >
          <FilePlus size={11} /> New File
        </button>
        <button
          onClick={() => { setCreating("folder"); setNewName(""); }}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: "1px solid #333", borderRadius: 4,
            cursor: "pointer", color: "#999", fontSize: 10, padding: "2px 8px",
          }}
        >
          <FolderPlus size={11} /> New Folder
        </button>
        <button
          onClick={() => refetch()}
          style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "none", border: "1px solid #333", borderRadius: 4,
            cursor: "pointer", color: "#999", fontSize: 10, padding: "2px 8px",
          }}
        >
          <RefreshCw size={10} />
        </button>
      </div>

      {/* Create inline form */}
      {creating && (
        <div style={{
          display: "flex", gap: 6, alignItems: "center",
          padding: "6px 10px", background: "#111", borderRadius: 6, border: "1px solid #333",
        }}>
          <span style={{ fontSize: 11, color: "#999" }}>
            {creating === "folder" ? "Folder:" : "File:"}
          </span>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") setCreating(null); }}
            placeholder={creating === "folder" ? "folder-name" : "filename.txt"}
            style={{
              flex: 1, background: "#0a0a0a", border: "1px solid #333", borderRadius: 4,
              padding: "3px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={handleCreate}
            disabled={!newName.trim() || mkdirMut.isPending || writeMut.isPending}
            style={{
              padding: "3px 10px", fontSize: 11, fontWeight: 600,
              background: newName.trim() ? "#3b82f6" : "#333",
              color: newName.trim() ? "#fff" : "#666",
              border: "none", borderRadius: 4, cursor: newName.trim() ? "pointer" : "not-allowed",
            }}
          >
            Create
          </button>
          <button
            onClick={() => setCreating(null)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#666", padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Entries */}
      {isLoading ? (
        <div style={{ color: "#555", fontSize: 12, padding: 12 }}>Loading...</div>
      ) : (
        <div style={{
          background: "#0a0a0a", borderRadius: 8, border: "1px solid #1a1a1a",
          overflow: "hidden",
        }}>
          {(!data?.entries || data.entries.length === 0) && (
            <div style={{ color: "#555", fontSize: 12, padding: 12 }}>Empty directory</div>
          )}
          {data?.entries?.map((entry) => (
            <div
              key={entry.path}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px",
                background: viewingFile === entry.path ? "rgba(59,130,246,0.08)" : "transparent",
                borderBottom: "1px solid #111",
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
                  <Folder size={13} color="#93c5fd" />
                ) : (
                  <FileText size={13} color="#666" />
                )}
                <span style={{
                  flex: 1, fontSize: 12, color: entry.is_dir ? "#e5e5e5" : "#999",
                  fontFamily: "monospace",
                }}>
                  {entry.name}
                </span>
                {!entry.is_dir && entry.size != null && (
                  <span style={{ fontSize: 10, color: "#555" }}>{formatSize(entry.size)}</span>
                )}
                {entry.is_dir && <ChevronRight size={12} color="#555" />}
              </button>
              <button
                onClick={() => handleDelete(entry.path, entry.name, entry.is_dir)}
                disabled={deleteMut.isPending}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "#444", padding: 2, flexShrink: 0,
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
          background: "#0a0a0a", borderRadius: 8, border: "1px solid #1a1a1a",
          overflow: "hidden",
        }}>
          {/* File header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 12px", borderBottom: "1px solid #1a1a1a",
            background: "#111",
          }}>
            <FileText size={13} color="#93c5fd" />
            <span style={{ flex: 1, fontSize: 12, color: "#e5e5e5", fontFamily: "monospace" }}>
              {viewingFile}
            </span>
            {fileData && !editing && (
              <button
                onClick={() => { setEditing(true); setEditContent(fileData.content); }}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "3px 10px", fontSize: 11, fontWeight: 600,
                  background: "transparent", border: "1px solid #333", borderRadius: 4,
                  color: "#999", cursor: "pointer",
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
                    background: "#3b82f6", border: "none", borderRadius: 4,
                    color: "#fff", cursor: "pointer",
                  }}
                >
                  <Save size={11} /> {writeMut.isPending ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setEditing(false)}
                  style={{
                    padding: "3px 10px", fontSize: 11,
                    background: "transparent", border: "1px solid #333", borderRadius: 4,
                    color: "#999", cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </>
            )}
            <button
              onClick={() => { setViewingFile(null); setEditing(false); }}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#666", padding: 2 }}
            >
              <X size={14} />
            </button>
          </div>

          {/* File content */}
          <div style={{ padding: 12, maxHeight: 400, overflowY: "auto" }}>
            {fileLoading && (
              <div style={{ color: "#555", fontSize: 12 }}>Loading file...</div>
            )}
            {fileError && (
              <div style={{ color: "#fca5a5", fontSize: 12 }}>
                {(fileError as any)?.message || "Failed to load file"}
              </div>
            )}
            {fileData && !editing && (
              <pre style={{
                color: "#ccc", fontSize: 12, fontFamily: "monospace",
                whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.5,
                wordBreak: "break-all",
              }}>
                {fileData.content || <span style={{ color: "#555" }}>(empty file)</span>}
              </pre>
            )}
            {editing && (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                style={{
                  width: "100%", minHeight: 200, background: "#0d0d0d",
                  border: "1px solid #333", borderRadius: 6,
                  padding: 10, color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
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
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: "1px solid #333", gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ChevronLeft size={22} color="#999" />
        </button>
        <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New Workspace" : "Edit Workspace"}
        </span>
        {!isNew && isWide && (
          <span style={{ color: "#555", fontSize: 11, fontFamily: "monospace" }}>
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
              border: "1px solid #7f1d1d", borderRadius: 6,
              background: "transparent", color: "#fca5a5", cursor: "pointer", flexShrink: 0,
            }}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
        )}
        {/* Unsaved indicator */}
        {isDirty && !isNew && !justSaved && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: "#fbbf24",
            flexShrink: 0, whiteSpace: "nowrap",
          }}>
            Unsaved changes
          </span>
        )}
        {justSaved && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: "#86efac",
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
            border: isDirty && canSave ? "2px solid #3b82f6" : "none",
            borderRadius: 6, flexShrink: 0,
            background: !canSave ? "#333" : isDirty ? "#3b82f6" : "#1e3a5f",
            color: !canSave ? "#666" : "#fff",
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
          fontSize: 12, color: "#fbbf24",
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
        <div style={{ padding: "8px 20px", background: "#7f1d1d", color: "#fca5a5", fontSize: 12 }}>
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
                      flex: 1, background: "#111",
                      border: `1px solid ${!p.host && p.container ? "#7f1d1d" : "#333"}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <span style={{ color: "#555" }}>:</span>
                  <input
                    value={p.container}
                    onChange={(e) => {
                      const next = [...ports];
                      next[i] = { ...next[i], container: e.target.value };
                      setPorts(next);
                    }}
                    placeholder="Container port"
                    style={{
                      flex: 1, background: "#111",
                      border: `1px solid ${p.host && !p.container ? "#7f1d1d" : "#333"}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <button
                    onClick={() => setPorts(ports.filter((_, j) => j !== i))}
                    style={{
                      background: "none", border: "none", cursor: "pointer",
                      color: "#666", padding: 2, flexShrink: 0,
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
                  border: "1px solid #333", borderRadius: 5,
                  background: "transparent", color: "#999", cursor: "pointer",
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
                      flex: 2, background: "#111",
                      border: `1px solid ${!m.host_path && m.container_path ? "#7f1d1d" : "#333"}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
                      outline: "none",
                    }}
                  />
                  <span style={{ color: "#555" }}>→</span>
                  <input
                    value={m.container_path}
                    onChange={(e) => {
                      const next = [...mounts];
                      next[i] = { ...next[i], container_path: e.target.value };
                      setMounts(next);
                    }}
                    placeholder="Container path"
                    style={{
                      flex: 2, background: "#111",
                      border: `1px solid ${m.host_path && !m.container_path ? "#7f1d1d" : "#333"}`,
                      borderRadius: 6,
                      padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
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
                      background: "#111", border: "1px solid #333", borderRadius: 5,
                      padding: "3px 6px", color: "#ccc", fontSize: 11, cursor: "pointer",
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
                      color: "#666", padding: 2, flexShrink: 0,
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
                  border: "1px solid #333", borderRadius: 5,
                  background: "transparent", color: "#999", cursor: "pointer",
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
              <Toggle value={skillsEnabled} onValueChange={setSkillsEnabled} />
            </FormRow>
            <div style={{ padding: "8px 0", fontSize: 12, color: "#888", lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: "#bbb", marginBottom: 4 }}>Directory conventions:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span><code style={{ color: "#93c5fd" }}>common/skills/pinned/*.md</code> — injected into every request</span>
                <span><code style={{ color: "#93c5fd" }}>common/skills/rag/*.md</code> — retrieved by similarity</span>
                <span><code style={{ color: "#93c5fd" }}>common/skills/on-demand/*.md</code> — available via tool call</span>
                <span><code style={{ color: "#93c5fd" }}>common/skills/*.md</code> — top-level defaults to pinned</span>
                <span style={{ marginTop: 4 }}><code style={{ color: "#fbbf24" }}>bots/&lt;bot-id&gt;/skills/...</code> — same structure, scoped to specific bot</span>
              </div>
            </div>
            {!isNew && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                <button
                  onClick={async () => {
                    try {
                      const resp = await fetch(
                        `${process.env.EXPO_PUBLIC_API_URL || ""}/api/v1/workspaces/${workspaceId}/reindex-skills`,
                        { method: "POST", headers: { Authorization: `Bearer ${process.env.EXPO_PUBLIC_API_KEY || ""}` } },
                      );
                      const data = await resp.json();
                      alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                    } catch (e) {
                      alert("Failed to reindex skills");
                    }
                  }}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "5px 12px", fontSize: 11, fontWeight: 600,
                    border: "1px solid #333", borderRadius: 5,
                    background: "transparent", color: "#999", cursor: "pointer",
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
              <Toggle value={basePromptEnabled} onValueChange={setBasePromptEnabled} />
            </FormRow>
            <div style={{ padding: "8px 0", fontSize: 12, color: "#888", lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: "#bbb", marginBottom: 4 }}>File conventions:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span><code style={{ color: "#93c5fd" }}>common/prompts/base.md</code> — replaces global base prompt for all workspace bots</span>
                <span><code style={{ color: "#fbbf24" }}>bots/&lt;bot-id&gt;/prompts/base.md</code> — concatenated after common, resolved per bot at runtime</span>
              </div>
            </div>
          </Section>

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
                    border: "1px solid #333", borderRadius: 5,
                    background: "transparent", color: "#999", cursor: "pointer",
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
                  <span style={{ color: "#666" }}>ID</span>
                  <span style={{ color: "#ccc", fontFamily: "monospace" }}>{workspace.id}</span>
                </div>
                {workspace.container_id && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#666" }}>Container</span>
                    <span style={{ color: "#888", fontFamily: "monospace" }}>
                      {workspace.container_name || workspace.container_id.slice(0, 12)}
                    </span>
                  </div>
                )}
                {workspace.image_id && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#666" }}>Image ID</span>
                    <span style={{ color: "#888", fontFamily: "monospace" }}>{workspace.image_id.slice(0, 16)}</span>
                  </div>
                )}
                {workspace.last_started_at && (
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#666" }}>Last Started</span>
                    <span style={{ color: "#888" }}>
                      {new Date(workspace.last_started_at).toLocaleString()}
                    </span>
                  </div>
                )}
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>Created</span>
                  <span style={{ color: "#888" }}>
                    {new Date(workspace.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>Updated</span>
                  <span style={{ color: "#888" }}>
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
