import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, RefreshCw, AlertTriangle, Search, TrendingUp } from "lucide-react";
import { useSkills, useFileSync, type SkillItem, type FileSyncResult } from "@/src/api/hooks/useSkills";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useState, useMemo } from "react";

function SourceBadge({ type, detail }: { type: string; detail?: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
    tool: { bg: "rgba(16,185,129,0.15)", fg: "#059669", label: "bot-authored" },
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

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const now = Date.now();
  const diffMs = now - d.getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return fmtDate(iso);
}

function SurfacingBadge({ count, lastAt, compact }: { count: number; lastAt?: string | null; compact?: boolean }) {
  const t = useThemeTokens();
  if (!count) {
    return (
      <span style={{ fontSize: 10, color: t.textDim }} title="Never surfaced in bot context">
        --
      </span>
    );
  }
  const isHot = count >= 10;
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 3,
        fontSize: 10, color: isHot ? "#059669" : t.textMuted,
      }}
      title={`Surfaced in bot context ${count} times — last ${fmtRelative(lastAt)}`}
    >
      {isHot && <TrendingUp size={10} />}
      {count}{!compact && <span style={{ fontSize: 9, color: t.textDim }}>surfaced</span>}
    </span>
  );
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "subheader"; key: string; label: string; count: number }
  | { type: "skill"; key: string; skill: SkillItem };

function SectionHeader({ label, count, level, isWide }: { label: string; count: number; level: number; isWide: boolean }) {
  const t = useThemeTokens();
  const isSubheader = level > 0;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: isWide
        ? `${isSubheader ? 8 : 14}px 16px ${isSubheader ? 4 : 6}px ${isSubheader ? 32 : 16}px`
        : `${isSubheader ? 8 : 14}px 0 ${isSubheader ? 4 : 6}px ${isSubheader ? 16 : 0}px`,
    }}>
      <span style={{
        fontSize: isSubheader ? 10 : 11,
        fontWeight: 600,
        color: isSubheader ? t.textDim : t.textMuted,
        textTransform: "uppercase",
        letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 10, color: t.textDim, fontWeight: 500,
      }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

function CategoryBadge({ category }: { category: string }) {
  const t = useThemeTokens();
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 500,
      background: t.surfaceOverlay, color: t.textMuted,
    }}>
      {category}
    </span>
  );
}

function SkillRow({ skill, onPress, isWide }: { skill: SkillItem; onPress: () => void; isWide: boolean }) {
  const t = useThemeTokens();
  const isBotAuthored = skill.source_type === "tool";
  const wsDetail = isBotAuthored && skill.bot_id
    ? `authored by ${skill.bot_id}`
    : undefined;
  const description = skill.description
    || (skill.content || "").split("\n").find((l) => l.trim() && !l.startsWith("#") && !l.startsWith("---"))?.trim()
    || "";

  if (!isWide) {
    // Mobile: card layout
    return (
      <button
        onClick={onPress}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
            {skill.name}
          </span>
          {skill.category && <CategoryBadge category={skill.category} />}
          <SourceBadge type={skill.source_type} detail={wsDetail} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: t.textDim }}>
          <span style={{ fontFamily: "monospace" }}>{skill.id}</span>
          <span>{skill.chunk_count} chunks</span>
          <SurfacingBadge count={skill.surface_count} lastAt={skill.last_surfaced_at} />
          {isBotAuthored && skill.bot_id && (
            <span style={{ color: "#059669" }}>{skill.bot_id}</span>
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
      onClick={onPress}
      style={{
        display: "grid", gridTemplateColumns: "140px 1fr 90px 60px 60px 100px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        border: "none",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left", width: "100%",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = t.inputBg; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {skill.id}
      </span>
      <div style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </span>
          {skill.category && <CategoryBadge category={skill.category} />}
          {isBotAuthored && skill.bot_id && (
            <span style={{ fontSize: 10, color: "#059669", whiteSpace: "nowrap" }}>{skill.bot_id}</span>
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
      <span style={{ textAlign: "right" }}>
        <SurfacingBadge count={skill.surface_count} lastAt={skill.last_surfaced_at} compact />
      </span>
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>{fmtDate(skill.updated_at)}</span>
    </button>
  );
}

function SyncResultBanner({ result, onDismiss }: { result: FileSyncResult; onDismiss: () => void }) {
  const t = useThemeTokens();
  const hasErrors = result.errors && result.errors.length > 0;
  const bg = hasErrors ? t.dangerSubtle : t.successSubtle;
  const border = hasErrors ? t.dangerBorder : t.successBorder;
  const color = hasErrors ? t.danger : t.success;
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
            <div key={i} style={{ color: t.danger, marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
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
        s.source_type.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q) ||
        (s.category || "").toLowerCase().includes(q) ||
        (s.triggers || []).some((t) => t.toLowerCase().includes(q)),
    );
  }, [skills, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filteredSkills.length) return [];

    const manual: SkillItem[] = [];
    const botAuthored: SkillItem[] = [];
    const core: SkillItem[] = [];
    const integrationMap = new Map<string, SkillItem[]>();

    for (const s of filteredSkills) {
      if (s.source_type === "tool") botAuthored.push(s);
      else if (s.source_type === "manual") manual.push(s);
      else if (s.source_type === "integration") {
        const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(name);
        if (list) list.push(s); else integrationMap.set(name, [s]);
      } else core.push(s);
    }

    // Sort bot-authored by most recent first
    botAuthored.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

    const items: RenderItem[] = [];

    const addGroup = (key: string, label: string, skills: SkillItem[]) => {
      if (!skills.length) return;
      items.push({ type: "header", key, label, count: skills.length });
      for (const s of skills) items.push({ type: "skill", key: s.id, skill: s });
    };

    addGroup("bot-authored", "Bot-Authored", botAuthored);
    addGroup("manual", "User Added", manual);
    addGroup("core", "Core", core);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt });
      for (const k of intKeys) {
        const skills = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: skills.length });
        for (const s of skills) items.push({ type: "skill", key: s.id, skill: s });
      }
    }

    return items;
  }, [filteredSkills]);

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
        <ActivityIndicator color={t.accent} />
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
        display: "flex", alignItems: "center", gap: 10,
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: isWide ? 300 : undefined, flex: isWide ? undefined : 1,
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
        {skills && skills.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {search && filteredSkills.length !== skills.length
              ? `${filteredSkills.length} / ${skills.length}`
              : skills.length}{" "}
            skills
          </span>
        )}
      </div>

      {/* Sync result banner */}
      {syncResult && (
        <SyncResultBanner result={syncResult} onDismiss={() => setSyncResult(null)} />
      )}
      {syncError && (
        <div style={{
          padding: "10px 16px", background: t.dangerSubtle,
          border: `1px solid ${t.dangerBorder}`,
          margin: "8px 12px 0", borderRadius: 8, fontSize: 12, color: t.danger,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span><AlertTriangle size={12} style={{ marginRight: 6 }} />Sync failed: {syncError}</span>
          <button onClick={() => setSyncError(null)} style={{
            background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16,
          }}>&times;</button>
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
        {/* Column headers (desktop only) */}
        {isWide && renderItems.length > 0 && (
          <div style={{
            display: "grid", gridTemplateColumns: "140px 1fr 90px 60px 60px 100px",
            gap: 12, padding: "6px 16px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1 }}>ID</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1 }}>Name</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1 }}>Source</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1, textAlign: "right" }}>Chunks</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1, textAlign: "right" }}>Surfaced</span>
            <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1, textAlign: "right" }}>Updated</span>
          </div>
        )}
        {renderItems.map((item) =>
          item.type === "header" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={0} isWide={isWide} />
          ) : item.type === "subheader" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={1} isWide={isWide} />
          ) : (
            <SkillRow
              key={item.key}
              skill={item.skill}
              isWide={isWide}
              onPress={() => router.push(`/admin/skills/${encodeURIComponent(item.skill.id)}` as any)}
            />
          ),
        )}
      </RefreshableScrollView>
    </View>
  );
}
