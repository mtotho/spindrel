import { useState, useMemo } from "react";
import { Search, BookOpen, TrendingUp, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills } from "@/src/api/hooks/useSkills";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { BotConfig, BotEditorData, SkillOption } from "@/src/types/api";
import { EnrolledSkillsPanel } from "./EnrolledSkillsPanel";

function SourceBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
    tool: { bg: "rgba(16,185,129,0.15)", fg: "#059669", label: "bot" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {c.label}
    </span>
  );
}

function StarterBadge() {
  return (
    <span
      title="Auto-enrolled into every new bot's working set"
      style={{
        padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
        background: "rgba(59,130,246,0.15)", color: "#2563eb",
      }}
    >
      starter
    </span>
  );
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: "10px 0 4px" }}>
      <span style={{ fontSize: 10, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

type GroupedItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "skill"; key: string; skill: SkillOption };

function groupSkills(skills: SkillOption[], botId?: string): GroupedItem[] {
  const ownBotAuthored: SkillOption[] = [];
  const core: SkillOption[] = [];
  const integrationMap = new Map<string, SkillOption[]>();

  for (const s of skills) {
    const sourceType = s.source_type || "manual";
    // Hide other bots' private skills entirely
    if (s.id.startsWith("bots/") && botId && !s.id.startsWith(`bots/${botId}/`)) {
      continue;
    }
    if (sourceType === "tool") {
      ownBotAuthored.push(s);
    } else if (sourceType === "integration") {
      const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
      const list = integrationMap.get(name);
      if (list) list.push(s); else integrationMap.set(name, [s]);
    } else {
      core.push(s);
    }
  }

  const items: GroupedItem[] = [];

  if (core.length > 0) {
    items.push({ type: "header", key: "core", label: "Core", count: core.length });
    for (const s of core) items.push({ type: "skill", key: s.id, skill: s });
  }

  const intKeys = [...integrationMap.keys()].sort();
  for (const k of intKeys) {
    const list = integrationMap.get(k)!;
    items.push({ type: "header", key: `int-${k}`, label: fmtIntName(k), count: list.length });
    for (const s of list) items.push({ type: "skill", key: s.id, skill: s });
  }

  if (ownBotAuthored.length > 0) {
    items.push({ type: "header", key: "bot-authored", label: "Self-Authored", count: ownBotAuthored.length });
    for (const s of ownBotAuthored) items.push({ type: "skill", key: s.id, skill: s });
  }

  return items;
}

function SelfAuthoredSkillsBanner({ botId, onNavigateToLearning }: { botId: string; onNavigateToLearning?: () => void }) {
  const t = useThemeTokens();
  const { data: botSkills } = useSkills({ bot_id: botId, source_type: "tool", sort: "recent" });

  if (!botSkills || botSkills.length === 0) return null;

  const totalSurfaced = botSkills.reduce((n, s) => n + s.surface_count, 0);

  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: "8px 12px",
      background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)",
      borderRadius: 8, marginBottom: 8,
    }}>
      <BookOpen size={13} color="#059669" />
      <span style={{ fontSize: 11, color: t.textMuted, flex: 1 }}>
        <strong style={{ color: "#059669" }}>{botSkills.length}</strong> bot-authored skill{botSkills.length !== 1 ? "s" : ""}
        {" — "}
        <TrendingUp size={10} color="#059669" style={{ verticalAlign: "middle", marginRight: 2 }} />
        <strong style={{ color: t.text }}>{totalSurfaced}</strong> surfacings
      </span>
      <button
        onClick={onNavigateToLearning}
        style={{
          fontSize: 11, color: t.accent, background: "none", border: "none",
          cursor: "pointer", fontWeight: 500, whiteSpace: "nowrap", padding: 0,
        }}
      >
        View Learning tab &rarr;
      </button>
    </div>
  );
}

export function SkillsSection({
  editorData, draft, update, onNavigateToLearning,
}: { editorData: BotEditorData; draft: BotConfig; update: (p: Partial<BotConfig>) => void; onNavigateToLearning?: () => void }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const list = filter
      ? editorData.all_skills.filter((s) =>
          s.id.toLowerCase().includes(filter.toLowerCase()) ||
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          (s.description || "").toLowerCase().includes(filter.toLowerCase()))
      : editorData.all_skills;
    return groupSkills(list, draft.id);
  }, [editorData.all_skills, filter, draft.id]);

  const starterIds = useMemo(
    () => new Set(editorData.starter_skill_ids ?? []),
    [editorData.starter_skill_ids],
  );

  const totalCount = editorData.all_skills.filter((s) =>
    s.source_type !== "tool" && !(s.id.startsWith("bots/") && draft.id && !s.id.startsWith(`bots/${draft.id}/`))
  ).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {draft.id && <SelfAuthoredSkillsBanner botId={draft.id} onNavigateToLearning={onNavigateToLearning} />}

      <div style={{ fontSize: 11, color: t.textDim }}>
        Skills are shared reference documents available to all bots via <code style={{ fontSize: 10 }}>get_skill()</code>.
        Foldered skills use <code style={{ fontSize: 10 }}>index.md</code> as the entry skill and sibling files as related sub-skills.
      </div>

      {draft.id && (
        <EnrolledSkillsPanel botId={draft.id} botName={draft.name} catalogSkills={editorData.all_skills} />
      )}

      <div style={{ fontSize: 11, color: t.textDim }}>
        <span style={{ color: t.textMuted, fontWeight: 500 }}>{totalCount}</span> skills available
      </div>

      {/* Full skill list */}
      <AdvancedSection title="All Skills" defaultOpen>
        <div style={{ paddingTop: 8 }}>
          {editorData.all_skills.length > 6 && (
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 8px",
            }}>
              <Search size={12} color={t.textDim} />
              <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter skills..." style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }} />
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 0 }}>
            {filtered.map((item) => {
              if (item.type === "header") {
                return <SectionHeader key={item.key} label={item.label} count={item.count} />;
              }
              const skill = item.skill;
              const desc = skill.description?.trim();
              const cleanedDesc = desc && desc !== "---" ? desc : null;
              const sourceType = skill.source_type || "manual";
              const isBotAuthored = sourceType === "tool";
              return (
                <div key={skill.id} style={{
                  padding: "8px 4px", borderRadius: 0,
                  background: isBotAuthored ? "rgba(16,185,129,0.06)" : "transparent",
                  borderBottom: `1px solid ${isBotAuthored ? "rgba(16,185,129,0.15)" : t.surfaceBorder}`,
                }}>
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 6 }}>
                    {isBotAuthored && (
                      <span style={{
                        display: "inline-flex", flexDirection: "row", alignItems: "center", fontSize: 9, fontWeight: 600,
                        color: "#059669", background: "rgba(16,185,129,0.15)", borderRadius: 3,
                        padding: "2px 5px", marginTop: 1, whiteSpace: "nowrap",
                      }}>
                        auto
                      </span>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, fontWeight: 500, color: t.text }}>{skill.name}</span>
                        <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{skill.id}</span>
                        {sourceType !== "integration" && !isBotAuthored && <SourceBadge type={sourceType} />}
                        {skill.skill_layout === "folder_root" && (
                          <span style={{ padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600, background: t.surfaceOverlay, color: t.textMuted }}>
                            folder
                          </span>
                        )}
                        {skill.skill_layout === "child" && (
                          <span style={{ padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600, background: t.surfaceOverlay, color: t.textMuted }}>
                            child
                          </span>
                        )}
                        {starterIds.has(skill.id) && <StarterBadge />}
                      </div>
                      {cleanedDesc && (
                        <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {cleanedDesc}
                        </div>
                      )}
                      {isBotAuthored && (
                        <div style={{ fontSize: 10, color: t.textDim, marginTop: 3 }}>
                          Bot-authored reference document.
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => navigate(`/admin/skills/${encodeURIComponent(skill.id)}`)}
                      style={{
                        display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
                        fontSize: 10, color: t.accent, background: "none",
                        border: "none", cursor: "pointer", whiteSpace: "nowrap", marginTop: 1,
                      }}
                    >
                      <ExternalLink size={10} />
                      View
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </AdvancedSection>
    </div>
  );
}
