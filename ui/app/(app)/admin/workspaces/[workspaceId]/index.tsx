import { useState, useCallback, useEffect } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  ChevronLeft, Trash2, Play, Square, RefreshCw, Download,
  Plus, X, FolderOpen, ChevronRight, FileText, Folder,
} from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import {
  useWorkspace, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
  useStartWorkspace, useStopWorkspace, useRecreateWorkspace,
  usePullWorkspaceImage, useWorkspaceStatus, useWorkspaceLogs,
  useAddBotToWorkspace, useUpdateWorkspaceBot, useRemoveBotFromWorkspace,
  useWorkspaceFiles, useReindexWorkspace,
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
function EnvEditor({ env, onChange }: {
  env: Record<string, string>;
  onChange: (env: Record<string, string>) => void;
}) {
  const entries = Object.entries(env);
  const addEntry = () => onChange({ ...env, "": "" });
  const removeEntry = (key: string) => {
    const next = { ...env };
    delete next[key];
    onChange(next);
  };
  const updateKey = (oldKey: string, newKey: string) => {
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(env)) {
      next[k === oldKey ? newKey : k] = v;
    }
    onChange(next);
  };
  const updateValue = (key: string, value: string) => {
    onChange({ ...env, [key]: value });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map(([key, value], i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={key}
            onChange={(e) => updateKey(key, e.target.value)}
            placeholder="KEY"
            style={{
              flex: 1, background: "#111", border: "1px solid #333", borderRadius: 6,
              padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <span style={{ color: "#555" }}>=</span>
          <input
            value={value}
            onChange={(e) => updateValue(key, e.target.value)}
            placeholder="value"
            style={{
              flex: 2, background: "#111", border: "1px solid #333", borderRadius: 6,
              padding: "5px 8px", color: "#e5e5e5", fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={() => removeEntry(key)}
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
        onClick={addEntry}
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
// File browser
// ---------------------------------------------------------------------------
function FileBrowser({ workspaceId }: { workspaceId: string }) {
  const [path, setPath] = useState("/");
  const { data, isLoading } = useWorkspaceFiles(workspaceId, path);

  const navigateTo = (entryPath: string) => setPath(entryPath);
  const navigateUp = () => {
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    setPath(parent);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
        <button
          onClick={() => setPath("/")}
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
      </div>

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
            <button
              key={entry.path}
              onClick={() => entry.is_dir && navigateTo(entry.path)}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px", width: "100%",
                background: "transparent", border: "none",
                borderBottom: "1px solid #111",
                cursor: entry.is_dir ? "pointer" : "default",
                textAlign: "left",
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
                <span style={{ fontSize: 10, color: "#555" }}>
                  {entry.size > 1024 * 1024
                    ? `${(entry.size / (1024 * 1024)).toFixed(1)}M`
                    : entry.size > 1024
                      ? `${(entry.size / 1024).toFixed(1)}K`
                      : `${entry.size}B`}
                </span>
              )}
              {entry.is_dir && <ChevronRight size={12} color="#555" />}
            </button>
          ))}
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
  const [env, setEnv] = useState<Record<string, string>>({});
  const [cpus, setCpus] = useState("");
  const [memoryLimit, setMemoryLimit] = useState("");
  const [dockerUser, setDockerUser] = useState("");
  const [readOnlyRoot, setReadOnlyRoot] = useState(false);
  const [initialized, setInitialized] = useState(isNew);

  if (workspace && !initialized) {
    setName(workspace.name || "");
    setDescription(workspace.description || "");
    setImage(workspace.image || "agent-workspace:latest");
    setNetwork(workspace.network || "none");
    setEnv(workspace.env || {});
    setCpus(workspace.cpus ? String(workspace.cpus) : "");
    setMemoryLimit(workspace.memory_limit || "");
    setDockerUser(workspace.docker_user || "");
    setReadOnlyRoot(workspace.read_only_root || false);
    setInitialized(true);
  }

  const currentStatus = liveStatus?.status || workspace?.status || "stopped";

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!name.trim()) return;
      await createMut.mutateAsync({
        name: name.trim(),
        description: description || undefined,
        image: image || undefined,
        network: network || undefined,
        env: Object.keys(env).length ? env : undefined,
        cpus: cpus ? parseFloat(cpus) : undefined,
        memory_limit: memoryLimit || undefined,
        docker_user: dockerUser || undefined,
        read_only_root: readOnlyRoot,
      });
      goBack();
    } else {
      await updateMut.mutateAsync({
        name: name.trim() || undefined,
        description,
        image: image || undefined,
        network: network || undefined,
        env: Object.keys(env).length ? env : undefined,
        cpus: cpus ? parseFloat(cpus) : undefined,
        memory_limit: memoryLimit || undefined,
        docker_user: dockerUser || undefined,
        read_only_root: readOnlyRoot,
      });
    }
  }, [isNew, name, description, image, network, env, cpus, memoryLimit, dockerUser, readOnlyRoot, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!workspaceId || !confirm("Delete this workspace? The container and data will be removed.")) return;
    await deleteMut.mutateAsync(workspaceId);
    goBack();
  }, [workspaceId, deleteMut, goBack]);

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
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}>
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
        <button
          onClick={handleSave}
          disabled={isSaving || !canSave}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: !canSave ? "#333" : "#3b82f6",
            color: !canSave ? "#666" : "#fff",
            cursor: !canSave ? "not-allowed" : "pointer",
          }}
        >
          {isSaving ? "..." : "Save"}
        </button>
      </div>

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
            <EnvEditor env={env} onChange={setEnv} />
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
