import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, Play, Square, Container, RefreshCw } from "lucide-react";
import { useWorkspaces, useStartWorkspace, useStopWorkspace } from "@/src/api/hooks/useWorkspaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import type { SharedWorkspace } from "@/src/types/api";

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
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg, whiteSpace: "nowrap",
    }}>
      {status}
    </span>
  );
}

function WorkspaceCard({ workspace, onPress, isWide }: {
  workspace: SharedWorkspace;
  onPress: () => void;
  isWide: boolean;
}) {
  return (
    <button
      onClick={onPress}
      style={{
        display: "flex", flexDirection: "column", gap: 10,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: "#111", borderRadius: 10,
        border: "1px solid #1a1a1a",
        cursor: "pointer", textAlign: "left", width: "100%",
      }}
    >
      {/* Top row: name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Container size={14} color="#93c5fd" />
        <span style={{ fontSize: 14, fontWeight: 600, color: "#e5e5e5", flex: 1 }}>
          {workspace.name}
        </span>
        <StatusBadge status={workspace.status} />
      </div>

      {/* Description */}
      {workspace.description && (
        <div style={{ fontSize: 12, color: "#888", lineHeight: 1.4 }}>
          {workspace.description.length > 120
            ? workspace.description.slice(0, 120) + "..."
            : workspace.description}
        </div>
      )}

      {/* Info row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 11, color: "#666" }}>
        <span style={{ fontFamily: "monospace" }}>{workspace.image}</span>
        {workspace.bots.length > 0 && (
          <span>{workspace.bots.length} bot{workspace.bots.length !== 1 ? "s" : ""}</span>
        )}
        {workspace.network !== "none" && (
          <span>net: {workspace.network}</span>
        )}
        {workspace.cpus && <span>{workspace.cpus} CPU</span>}
        {workspace.memory_limit && <span>{workspace.memory_limit} RAM</span>}
      </div>

      {/* Bots */}
      {workspace.bots.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {workspace.bots.map((b) => (
            <span key={b.bot_id} style={{
              padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 500,
              background: b.role === "orchestrator" ? "rgba(168,85,247,0.15)" : "rgba(59,130,246,0.1)",
              color: b.role === "orchestrator" ? "#c4b5fd" : "#93c5fd",
            }}>
              {b.bot_name || b.bot_id}
              {b.role === "orchestrator" && " (orch)"}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

export default function WorkspacesScreen() {
  const router = useRouter();
  const { data: workspaces, isLoading } = useWorkspaces();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Workspaces"
        right={
          <button
            onClick={() => router.push("/admin/workspaces/new" as any)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: "#3b82f6", color: "#fff", cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New Workspace
          </button>
        }
      />

      {/* Cards */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 20 : 12,
        gap: isWide ? 12 : 10,
      }}>
        {(!workspaces || workspaces.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", fontSize: 13,
          }}>
            <div style={{ color: "#555", marginBottom: 8 }}>No shared workspaces yet.</div>
            <div style={{ color: "#444", fontSize: 12 }}>
              Create a workspace to give multiple bots a shared Docker environment.
            </div>
          </div>
        )}

        {workspaces && workspaces.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(380px, 1fr))" : "1fr",
            gap: isWide ? 12 : 10,
          }}>
            {workspaces.map((ws) => (
              <WorkspaceCard
                key={ws.id}
                workspace={ws}
                isWide={isWide}
                onPress={() => router.push(`/admin/workspaces/${ws.id}` as any)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>
    </View>
  );
}
