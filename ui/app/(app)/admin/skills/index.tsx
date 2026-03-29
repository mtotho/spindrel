import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, RefreshCw, BookOpen, FileText, Plug, AlertTriangle, Search } from "lucide-react";
import { useSkills, useFileSync, type SkillItem, type FileSyncResult } from "@/src/api/hooks/useSkills";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useState, useMemo } from "react";

function SourceBadge({ type, detail }: { type: string; detail?: string }) {
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: "rgba(59,130,246,0.15)", fg: "#2563eb", label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: "rgba(100,100,100,0.15)", fg: "#999", label: "manual" },
    workspace: { bg: "rgba(168,85,247,0.15)", fg: "#9333ea", label: "workspace" },
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
  const t = useThemeTokens();
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
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${isWs ? "#2d1f4e" : t.surfaceRaised}`, cursor: isWs ? "default" : "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
            {skill.name}
          </span>
          <SourceBadge type={skill.source_type} detail={wsDetail} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: t.textDim }}>
          <span style={{ fontFamily: "monospace" }}>{skill.id}</span>
          <span>{skill.chunk_count} chunks</span>
          {isWs && skill.workspace_name && (
            <span style={{ color: "#9333ea" }}>{skill.workspace_name}</span>
          )}
        </div>
        {description && (
          <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
        borderBottom: `1px solid ${isWs ? "#1a1a2e" : t.surfaceRaised}`, cursor: isWs ? "default" : "pointer",
        textAlign: "left", width: "100%", border: "none",
      }}
      onMouseEnter={(e) => { if (!isWs) e.currentTarget.style.background = t.inputBg; }}
      onMouseLeave={(e) => { if (!isWs) e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {skill.id}
      </span>
      <div style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </span>
          {isWs && skill.workspace_name && (
            <span style={{ fontSize: 10, color: "#9333ea", whiteSpace: "nowrap" }}>{skill.workspace_name}</span>
          )}
        </div>
        {description && (
          <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
            {description.slice(0, 120)}
          </div>
        )}
      </div>
      <SourceBadge type={skill.source_type} detail={wsDetail} />
      <span style={{ fontSize: 11, color: t.textMuted, textAlign: "right" }}>{skill.chunk_count}</span>
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>{fmtDate(skill.updated_at)}</span>
    </button>
  );
}

function SyncResultBanner({ result, onDismiss }: { result: FileSyncResult; onDismiss: () => void }) {
  const t = useThemeTokens();
  const hasErrors = result.errors && result.errors.length > 0;
  const bg = hasErrors ? "rgba(127,29,29,0.3)" : "rgba(34,197,94,0.1)";
  const border = hasErrors ? "rgba(239,68,68,0.3)" : "rgba(34,197,94,0.2)";
  const color = hasErrors ? "#dc2626" : "#16a34a";
  return (
    <div style={{
      padding: "10px 16px", background: bg, border: `1px solid ${border}`,
      margin: "8px 12px 0", borderRadius: 8, fontSize: 12, color, lineHeight: 1.6,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong>Sync complete:</strong> +{result.added} added, ~{result.updated} updated,
          {" "}{result.unchanged} unchanged, -{result.deleted} deleted
          {result._diagnostics && (
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>
              {result._diagnostics.files_on_disk.length} files found on disk
              {" "}(cwd: <code>{result._diagnostics.cwd}</code>)
            </div>
          )}
          {hasErrors && result.errors.map((e, i) => (
            <div key={i} style={{ color: "#dc2626", marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
              <AlertTriangle size={12} /> {e}
            </div>
          ))}
        </div>
        <button onClick={onDismiss} style={{
          background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16, padding: "0 4px",
        }}>&times;</button>
      </div>
    </div>
  );
}

export default function SkillsScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: skills, isLoading } = useSkills();
  const syncMut = useFileSync();
  const [syncResult, setSyncResult] = useState<FileSyncResult | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");

  const filteredSkills = useMemo(() => {
    if (!skills) return [];
    if (!search.trim()) return skills;
    const q = search.toLowerCase();
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q) ||
        s.source_type.toLowerCase().includes(q),
    );
  }, [skills, search]);

  const handleSync = () => {
    setSyncResult(null);
    setSyncError(null);
    syncMut.mutate(undefined, {
      onSuccess: (data) => setSyncResult(data),
      onError: (err) => setSyncError((err as Error).message || "Sync failed"),
    });
  };

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
              onClick={handleSync}
              disabled={syncMut.isPending}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                background: "transparent", color: t.textMuted, cursor: "pointer",
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
                background: t.accent, color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New Skill
            </button>
          </div>
        }
      />

      {/* Search bar */}
      <div style={{
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: isWide ? 300 : undefined,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter skills..."
            style={{
              background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, flex: 1, width: "100%",
            }}
          />
        </div>
      </div>

      {/* Sync result banner */}
      {syncResult && (
        <SyncResultBanner result={syncResult} onDismiss={() => setSyncResult(null)} />
      )}
      {syncError && (
        <div style={{
          padding: "10px 16px", background: "rgba(127,29,29,0.3)",
          border: "1px solid rgba(239,68,68,0.3)",
          margin: "8px 12px 0", borderRadius: 8, fontSize: 12, color: "#dc2626",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span><AlertTriangle size={12} style={{ marginRight: 6 }} />Sync failed: {syncError}</span>
          <button onClick={() => setSyncError(null)} style={{
            background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16,
          }}>&times;</button>
        </div>
      )}

      {/* Table header (desktop only) */}
      {isWide && filteredSkills.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "140px 1fr 90px 60px 100px",
          gap: 12, padding: "8px 16px",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1,
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
            padding: 40, textAlign: "center", color: t.textDim, fontSize: 13,
          }}>
            No skills yet. Create one or drop <code style={{ color: t.textMuted }}>.md</code> files in{" "}
            <code style={{ color: t.textMuted }}>skills/</code> and click Sync Files.
          </div>
        )}
        {skills && skills.length > 0 && filteredSkills.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No skills match "{search}"
          </div>
        )}
        {filteredSkills.map((skill) => (
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
