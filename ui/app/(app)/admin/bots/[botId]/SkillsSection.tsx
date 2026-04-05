import { useState, useMemo } from "react";
import { Search, Zap, BookOpen, TrendingUp, ExternalLink } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills } from "@/src/api/hooks/useSkills";
import type { BotConfig, BotEditorData, SkillOption } from "@/src/types/api";

const AUTO_INJECTED_SKILLS: Record<string, string> = {
  "integrations/mission_control/mission_control":
    "Auto-injected via mission-control carapace for workspace-enabled channels",
};

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

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0 4px" }}>
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

function groupSkills(skills: SkillOption[]): GroupedItem[] {
  const botAuthored: SkillOption[] = [];
  const core: SkillOption[] = [];
  const integrationMap = new Map<string, SkillOption[]>();

  for (const s of skills) {
    const sourceType = s.source_type || "manual";
    if (sourceType === "tool") {
      botAuthored.push(s);
    } else if (sourceType === "integration") {
      const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
      const list = integrationMap.get(name);
      if (list) list.push(s); else integrationMap.set(name, [s]);
    } else {
      core.push(s);
    }
  }

  const items: GroupedItem[] = [];

  if (botAuthored.length > 0) {
    items.push({ type: "header", key: "bot-authored", label: "Bot Authored", count: botAuthored.length });
    for (const s of botAuthored) items.push({ type: "skill", key: s.id, skill: s });
  }

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

  return items;
}

function SelfAuthoredSkillsBanner({ botId, onNavigateToLearning }: { botId: string; onNavigateToLearning?: () => void }) {
  const t = useThemeTokens();
  const { data: botSkills } = useSkills({ bot_id: botId, source_type: "tool", sort: "recent" });

  if (!botSkills || botSkills.length === 0) return null;

  const totalSurfaced = botSkills.reduce((n, s) => n + s.surface_count, 0);

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
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
  const router = useRouter();
  const [filter, setFilter] = useState("");
  const skills = draft.skills || [];
  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const toggle = (id: string) => {
    update({
      skills: isSelected(id)
        ? skills.filter((s) => s.id !== id)
        : [...skills, { id, mode: "on_demand" }],
    });
  };

  const setMode = (id: string, mode: string) => {
    update({
      skills: skills.map((s) =>
        s.id === id ? { ...s, mode } : s
      ),
    });
  };

  const filtered = useMemo(() => {
    const list = filter
      ? editorData.all_skills.filter((s) =>
          s.id.toLowerCase().includes(filter.toLowerCase()) ||
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          (s.description || "").toLowerCase().includes(filter.toLowerCase()))
      : editorData.all_skills;
    return groupSkills(list);
  }, [editorData.all_skills, filter]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {draft.id && <SelfAuthoredSkillsBanner botId={draft.id} onNavigateToLearning={onNavigateToLearning} />}
      <div style={{ fontSize: 11, color: t.textDim }}>
        <strong style={{ color: t.textMuted }}>on_demand</strong> (default): index injected, agent calls get_skill.{" "}
        <strong style={{ color: t.textMuted }}>pinned</strong>: full content every turn.
      </div>
      {editorData.all_skills.length > 6 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
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
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          const autoNote = AUTO_INJECTED_SKILLS[skill.id];
          const desc = skill.description?.trim();
          const cleanedDesc = desc && desc !== "---" ? desc : null;
          const sourceType = skill.source_type || "manual";
          const isBotAuthored = sourceType === "tool";
          return (
            <div key={skill.id} style={{
              padding: "8px 4px", borderRadius: 0,
              background: isBotAuthored ? "rgba(16,185,129,0.06)" : sel ? t.accentSubtle : autoNote && !sel ? t.surfaceOverlay : "transparent",
              borderBottom: `1px solid ${isBotAuthored ? "rgba(16,185,129,0.15)" : sel ? t.accentBorder : t.surfaceBorder}`,
              opacity: autoNote && !sel ? 0.7 : 1,
            }}>
              {isBotAuthored ? (
                <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                  <span style={{
                    display: "inline-flex", alignItems: "center", fontSize: 9, fontWeight: 600,
                    color: "#059669", background: "rgba(16,185,129,0.15)", borderRadius: 3,
                    padding: "2px 5px", marginTop: 1, whiteSpace: "nowrap",
                  }}>
                    enabled
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: t.text }}>{skill.name}</span>
                      <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{skill.id}</span>
                    </div>
                    {cleanedDesc && (
                      <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {cleanedDesc}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 3 }}>
                      Auto-injected. Managed by the bot.
                    </div>
                  </div>
                  <button
                    onClick={() => router.push(`/admin/skills/${encodeURIComponent(skill.id)}` as any)}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 3,
                      fontSize: 10, color: t.accent, background: "none",
                      border: "none", cursor: "pointer", whiteSpace: "nowrap", marginTop: 1,
                    }}
                  >
                    <ExternalLink size={10} />
                    Edit
                  </button>
                </div>
              ) : (
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={sel} onChange={() => toggle(skill.id)} style={{ accentColor: t.accent, marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: sel ? t.accent : t.text }}>{skill.name}</span>
                    <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{skill.id}</span>
                    {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                    {autoNote && !sel && (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 3,
                        fontSize: 9, fontWeight: 600, color: t.accent,
                        background: `${t.accent}15`, borderRadius: 4, padding: "1px 5px",
                      }}>
                        <Zap size={8} />
                        AUTO
                      </span>
                    )}
                  </div>
                  {autoNote && !sel ? (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                      {autoNote}
                    </div>
                  ) : cleanedDesc ? (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {cleanedDesc}
                    </div>
                  ) : null}
                </div>
              </label>
              )}
              {sel && entry && !isBotAuthored && (
                <div style={{ marginTop: 6, marginLeft: 22 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted, cursor: "pointer" }}>
                    <input type="checkbox" checked={entry.mode === "pinned"}
                      onChange={(e) => setMode(skill.id, e.target.checked ? "pinned" : "on_demand")}
                      style={{ accentColor: t.accent }} />
                    pin (full content every turn)
                  </label>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
