import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  Trash2, Play, Square, RefreshCw, Download,
  FileText, AlertCircle,
} from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { DetailHeader } from "@/src/components/layout/DetailHeader";
import {
  useWorkspace, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
  useStartWorkspace, useStopWorkspace, useRecreateWorkspace,
  usePullWorkspaceImage, useWorkspaceStatus, useWorkspaceLogs,
} from "@/src/api/hooks/useWorkspaces";
import type { SharedWorkspace } from "@/src/types/api";
import {
  FormRow, TextInput, Section, TabBar,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

// Tab components
import { DockerTab } from "./DockerTab";
import { BotsTab } from "./BotsTab";
import { SkillsTab } from "./SkillsTab";
import { FilesTab } from "./FilesTab";
import { IndexingTab } from "./IndexingTab";
import { EditorTab } from "./EditorTab";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
function getStatusColors(t: ReturnType<typeof useThemeTokens>): Record<string, { bg: string; fg: string }> {
  return {
    running: { bg: t.successSubtle, fg: t.success },
    stopped: { bg: "rgba(100,100,100,0.15)", fg: "#999" },
    creating: { bg: t.accentSubtle, fg: t.accent },
    error: { bg: t.dangerSubtle, fg: t.danger },
  };
}

function StatusBadge({ status }: { status: string }) {
  const t = useThemeTokens();
  const statusColors = getStatusColors(t);
  const c = statusColors[status] || statusColors.stopped;
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
// Tab definitions
// ---------------------------------------------------------------------------
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "docker", label: "Docker" },
  { key: "bots", label: "Bots" },
  { key: "skills", label: "Skills" },
  { key: "files", label: "Files" },
  { key: "indexing", label: "Indexing" },
  { key: "editor", label: "Editor" },
];

const NEW_TABS = [
  { key: "overview", label: "Overview" },
  { key: "docker", label: "Docker" },
  { key: "skills", label: "Skills" },
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function WorkspaceDetailScreen() {
  const t = useThemeTokens();
  const { workspaceId } = useLocalSearchParams<{ workspaceId: string }>();
  const isNew = workspaceId === "new";
  const goBack = useGoBack("/admin/workspaces");
  const { data: workspace, isLoading } = useWorkspace(isNew ? undefined : workspaceId);
  const { data: liveStatus } = useWorkspaceStatus(
    !isNew && workspace ? workspaceId : undefined
  );
  const createMut = useCreateWorkspace();
  const updateMut = useUpdateWorkspace(workspaceId!);
  const deleteMut = useDeleteWorkspace();

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const [activeTab, setActiveTab] = useState("overview");

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
  const [writeProtectedPaths, setWriteProtectedPaths] = useState<string[]>([]);
  const [dbSkills, setDbSkills] = useState<{ id: string; mode?: string }[]>([]);
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
    setWriteProtectedPaths(workspace.write_protected_paths || []);
    setDbSkills(workspace.skills || []);
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
        write_protected_paths: writeProtectedPaths,
        skills: dbSkills.length ? dbSkills : undefined,
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
        write_protected_paths: writeProtectedPaths,
        skills: dbSkills,
      });
      // Update snapshot so dirty tracking resets
      savedSnapshot.current = currentSnapshot;
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2000);
    }
  }, [isNew, name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled, writeProtectedPaths, dbSkills, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!workspaceId || !confirm("Delete this workspace? The container and data will be removed.")) return;
    await deleteMut.mutateAsync(workspaceId);
    goBack();
  }, [workspaceId, deleteMut, goBack]);

  // -- Dirty tracking: compare current form state to last-saved snapshot --
  const savedSnapshot = useRef<string>("");
  const currentSnapshot = useMemo(() =>
    JSON.stringify({ name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled, writeProtectedPaths, dbSkills }),
    [name, description, image, network, env, ports, mounts, cpus, memoryLimit, dockerUser, readOnlyRoot, startupScript, skillsEnabled, basePromptEnabled, writeProtectedPaths, dbSkills],
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

  const activeTabs = isNew ? NEW_TABS : TABS;

  return (
    <View className="flex-1 bg-surface">
      <DetailHeader
        parentLabel="Workspaces"
        parentHref="/admin/workspaces"
        title={isNew ? "New Workspace" : "Edit Workspace"}
        subtitle={!isNew ? workspaceId?.slice(0, 8) : undefined}
        right={
          <>
            {!isNew && <StatusBadge status={currentStatus} />}
            {!isNew && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                title="Delete"
                style={{
                  display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
                  padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
                  border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                  background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
                }}
              >
                <Trash2 size={14} />
                {isWide && "Delete"}
              </button>
            )}
            {isDirty && !isNew && !justSaved && (
              <span style={{
                fontSize: 11, fontWeight: 600, color: t.warningMuted,
                flexShrink: 0, whiteSpace: "nowrap",
              }}>
                Unsaved changes
              </span>
            )}
            {justSaved && (
              <span style={{
                fontSize: 11, fontWeight: 600, color: t.success,
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
          </>
        }
      />

      {/* Tab bar */}
      <div style={{
        padding: isWide ? "8px 20px 0" : "6px 12px 0",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <TabBar tabs={activeTabs} active={activeTab} onChange={setActiveTab} />
      </div>

      {/* Validation warnings bar */}
      {hasWarnings && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "6px 20px", background: t.warningSubtle,
          borderBottom: `1px solid ${t.warningBorder}`,
          fontSize: 12, color: t.warningMuted,
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
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        paddingVertical: isWide ? 20 : 12,
        paddingHorizontal: isWide ? 24 : 12,
        maxWidth: 800,
      }}>
        {/* ---- Overview Tab ---- */}
        {activeTab === "overview" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <Section title="Identity">
              <FormRow label="Name" description="Unique workspace name">
                <TextInput value={name} onChangeText={setName} placeholder="e.g. my-workspace" />
              </FormRow>
              <FormRow label="Description">
                <TextInput value={description} onChangeText={setDescription} placeholder="Optional description" />
              </FormRow>
            </Section>

            {/* Container controls (only for existing workspaces) */}
            {!isNew && (
              <Section title="Container Controls">
                <ContainerControls workspaceId={workspaceId!} status={currentStatus} />
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
        )}

        {/* ---- Docker Tab ---- */}
        {activeTab === "docker" && (
          <DockerTab
            image={image} setImage={setImage}
            network={network} setNetwork={setNetwork}
            dockerUser={dockerUser} setDockerUser={setDockerUser}
            startupScript={startupScript} setStartupScript={setStartupScript}
            cpus={cpus} setCpus={setCpus}
            memoryLimit={memoryLimit} setMemoryLimit={setMemoryLimit}
            readOnlyRoot={readOnlyRoot} setReadOnlyRoot={setReadOnlyRoot}
            env={env} setEnv={setEnv}
            ports={ports} setPorts={setPorts}
            mounts={mounts} setMounts={setMounts}
          />
        )}

        {/* ---- Bots Tab ---- */}
        {activeTab === "bots" && !isNew && workspace && (
          <BotsTab
            workspaceId={workspaceId!}
            bots={workspace.bots}
            writeProtectedPaths={workspace.write_protected_paths || []}
          />
        )}

        {/* ---- Skills Tab ---- */}
        {activeTab === "skills" && (
          <SkillsTab
            workspaceId={workspaceId!}
            isNew={isNew}
            skillsEnabled={skillsEnabled}
            setSkillsEnabled={setSkillsEnabled}
            basePromptEnabled={basePromptEnabled}
            setBasePromptEnabled={setBasePromptEnabled}
            dbSkills={dbSkills}
            setDbSkills={setDbSkills}
          />
        )}

        {/* ---- Files Tab ---- */}
        {activeTab === "files" && !isNew && (
          <FilesTab
            workspaceId={workspaceId!}
            currentStatus={currentStatus}
          />
        )}

        {/* ---- Indexing Tab ---- */}
        {activeTab === "indexing" && !isNew && (
          <IndexingTab
            workspaceId={workspaceId!}
            writeProtectedPaths={writeProtectedPaths}
            setWriteProtectedPaths={setWriteProtectedPaths}
          />
        )}

        {/* ---- Editor Tab ---- */}
        {activeTab === "editor" && !isNew && workspace && (
          <EditorTab workspace={workspace} currentStatus={currentStatus} />
        )}
      </ScrollView>
    </View>
  );
}
