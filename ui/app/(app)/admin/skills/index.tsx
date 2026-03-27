import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, RefreshCw, BookOpen, FileText, Plug } from "lucide-react";
import { useSkills, useFileSync, type SkillItem } from "@/src/api/hooks/useSkills";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

function SourceBadge({ type, detail }: { type: string; detail?: string }) {
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: "rgba(59,130,246,0.15)", fg: "#93c5fd", label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#fdba74", label: "integration" },
    manual: { bg: "rgba(100,100,100,0.15)", fg: "#999", label: "manual" },
    workspace: { bg: "rgba(168,85,247,0.15)", fg: "#c084fc", label: "workspace" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}
      title={detail || undefined}
    >
      {c.label}
    </span>
  );
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

function SkillRow({ skill, onPress, isWide }: { skill: SkillItem; onPress: () => void; isWide: boolean }) {
  const firstLine = (skill.content || "").split("\n").find((l) => l.trim() && !l.startsWith("#"))?.trim() || "";
  const isWs = skill.source_type === "workspace";
  const wsDetail = isWs
    ? `${skill.workspace_name || "workspace"}${skill.bot_id ? ` / ${skill.bot_id}` : ""} (${skill.mode})`
    : undefined;
  const description = isWs
    ? `${skill.source_path}${skill.mode ? ` \u2022 ${skill.mode}` : ""}`
    : firstLine;

  if (!isWide) {
    // Mobile: card layout
    return (
      <button
        onClick={isWs ? undefined : onPress}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: "#111", borderRadius: 8,
          border: `1px solid ${isWs ? "#2d1f4e" : "#1a1a1a"}`, cursor: isWs ? "default" : "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5", flex: 1 }}>
            {skill.name}
          </span>
          <SourceBadge type={skill.source_type} detail={wsDetail} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: "#666" }}>
          <span style={{ fontFamily: "monospace" }}>{skill.id}</span>
          <span>{skill.chunk_count} chunks</span>
          {isWs && skill.workspace_name && (
            <span style={{ color: "#c084fc" }}>{skill.workspace_name}</span>
          )}
        </div>
        {description && (
          <div style={{ fontSize: 11, color: "#555", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {description.slice(0, 120)}
          </div>
        )}
      </button>
    );
  }

  // Desktop: table row
  return (
    <button
      onClick={isWs ? undefined : onPress}
      style={{
        display: "grid", gridTemplateColumns: "140px 1fr 90px 60px 100px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        borderBottom: `1px solid ${isWs ? "#1a1a2e" : "#1a1a1a"}`, cursor: isWs ? "default" : "pointer",
        textAlign: "left", width: "100%", border: "none",
      }}
      onMouseEnter={(e) => { if (!isWs) e.currentTarget.style.background = "#111"; }}
      onMouseLeave={(e) => { if (!isWs) e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ fontSize: 11, fontFamily: "monospace", color: "#888", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {skill.id}
      </span>
      <div style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </span>
          {isWs && skill.workspace_name && (
            <span style={{ fontSize: 10, color: "#c084fc", whiteSpace: "nowrap" }}>{skill.workspace_name}</span>
          )}
        </div>
        {description && (
          <div style={{ fontSize: 11, color: "#555", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
            {description.slice(0, 120)}
          </div>
        )}
      </div>
      <SourceBadge type={skill.source_type} detail={wsDetail} />
      <span style={{ fontSize: 11, color: "#888", textAlign: "right" }}>{skill.chunk_count}</span>
      <span style={{ fontSize: 11, color: "#666", textAlign: "right" }}>{fmtDate(skill.updated_at)}</span>
    </button>
  );
}

export default function SkillsScreen() {
  const router = useRouter();
  const { data: skills, isLoading } = useSkills();
  const syncMut = useFileSync();
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
        title="Skills"
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => syncMut.mutate()}
              disabled={syncMut.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "1px solid #333", borderRadius: 6,
                background: "transparent", color: "#999", cursor: "pointer",
              }}
            >
              <RefreshCw size={14} style={syncMut.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
              {syncMut.isPending ? "Syncing..." : "Sync"}
            </button>
            <button
              onClick={() => router.push("/admin/skills/new" as any)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: "#3b82f6", color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New Skill
            </button>
          </div>
        }
      />

      {/* Table header (desktop only) */}
      {isWide && skills && skills.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "140px 1fr 90px 60px 100px",
          gap: 12, padding: "8px 16px",
          borderBottom: "1px solid #222",
          fontSize: 10, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: 1,
        }}>
          <span>ID</span>
          <span>Name</span>
          <span>Source</span>
          <span style={{ textAlign: "right" }}>Chunks</span>
          <span style={{ textAlign: "right" }}>Updated</span>
        </div>
      )}

      {/* List */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 0 : 12,
        gap: isWide ? 0 : 8,
      }}>
        {(!skills || skills.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", color: "#555", fontSize: 13,
          }}>
            No skills yet. Create one or drop <code style={{ color: "#888" }}>.md</code> files in{" "}
            <code style={{ color: "#888" }}>skills/</code> and click Sync Files.
          </div>
        )}
        {skills?.map((skill) => (
          <SkillRow
            key={skill.id}
            skill={skill}
            isWide={isWide}
            onPress={() => router.push(`/admin/skills/${skill.id}` as any)}
          />
        ))}
      </RefreshableScrollView>
    </View>
  );
}
