import { useState, useMemo } from "react";
import { Search, BookOpen, TrendingUp, ExternalLink, Plus, X, Pin } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills } from "@/src/api/hooks/useSkills";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { BotConfig, BotEditorData, SkillOption } from "@/src/types/api";

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
  const [adding, setAdding] = useState(false);
  const [addSearch, setAddSearch] = useState("");
  const skills = draft.skills || [];
  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const setMode = (id: string, mode: string) => {
    update({
      skills: skills.map((s) =>
        s.id === id ? { ...s, mode } : s
      ),
    });
  };

  const pinnedSkills = useMemo(() => {
    return skills.filter((s) => s.mode === "pinned");
  }, [skills]);

  const pinnedSkillDetails = useMemo(() => {
    return pinnedSkills.map((s) => {
      const detail = editorData.all_skills.find((sk) => sk.id === s.id);
      return { ...s, name: detail?.name || s.id, description: detail?.description };
    });
  }, [pinnedSkills, editorData.all_skills]);

  const onDemandCount = useMemo(() => {
    const pinnedIds = new Set(pinnedSkills.map((s) => s.id));
    return editorData.all_skills.filter(
      (s) => s.source_type !== "tool" && !pinnedIds.has(s.id)
    ).length;
  }, [editorData.all_skills, pinnedSkills]);

  const unpinnedSkills = useMemo(() => {
    const pinnedIds = new Set(pinnedSkills.map((s) => s.id));
    return editorData.all_skills.filter(
      (s) => !pinnedIds.has(s.id) && s.source_type !== "tool"
    );
  }, [editorData.all_skills, pinnedSkills]);

  const filteredUnpinned = addSearch
    ? unpinnedSkills.filter((s) =>
        s.id.toLowerCase().includes(addSearch.toLowerCase()) ||
        s.name.toLowerCase().includes(addSearch.toLowerCase()) ||
        (s.description || "").toLowerCase().includes(addSearch.toLowerCase()))
    : unpinnedSkills;

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
        All skills auto-enroll as on-demand. Pin skills that should be in every conversation.
      </div>

      {/* Auto-enrolled count */}
      <div style={{ fontSize: 11, color: t.textDim }}>
        <span style={{ color: t.textMuted, fontWeight: 500 }}>{onDemandCount}</span> skills available on-demand (auto-enrolled)
      </div>

      {/* Pinned Skills */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Pinned Skills
        </div>
        {pinnedSkillDetails.length === 0 && !adding && (
          <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0 8px" }}>
            No pinned skills. All skills are available on-demand.
          </div>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {pinnedSkillDetails.map((s) => (
            <div key={s.id} style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 8px", borderRadius: 4, fontSize: 11,
              background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
            }}>
              <Pin size={9} color={t.accent} />
              <span style={{ color: t.accent, fontWeight: 500 }}>{s.name}</span>
              <button
                onClick={() => update({ skills: skills.filter((sk) => sk.id !== s.id) })}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}
                title="Unpin (remove — auto-enrollment handles on-demand)"
              >
                <X size={10} color={t.textDim} />
              </button>
            </div>
          ))}
          {!adding && (
            <button
              onClick={() => setAdding(true)}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "4px 8px", borderRadius: 4, fontSize: 11,
                background: "transparent", border: `1px dashed ${t.surfaceBorder}`,
                color: t.textDim, cursor: "pointer",
              }}
            >
              <Plus size={10} /> Pin a skill
            </button>
          )}
        </div>
        {adding && (
          <div style={{
            padding: 8, borderRadius: 6,
            border: `1px solid ${t.surfaceBorder}`, background: t.inputBg,
            marginBottom: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <Search size={12} color={t.textDim} />
              <input
                type="text" value={addSearch}
                onChange={(e) => setAddSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape") { setAdding(false); setAddSearch(""); } }}
                placeholder="Search skills to pin..."
                autoFocus
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
              />
              <button onClick={() => { setAdding(false); setAddSearch(""); }}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                <X size={12} color={t.textDim} />
              </button>
            </div>
            <div style={{ maxHeight: 200, overflow: "auto" }}>
              {filteredUnpinned.map((s) => (
                <button key={s.id} onClick={() => {
                  // If not selected, add as pinned
                  if (!isSelected(s.id)) {
                    update({ skills: [...skills, { id: s.id, mode: "pinned" }] });
                  } else {
                    setMode(s.id, "pinned");
                  }
                  setAddSearch("");
                }}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    width: "100%", textAlign: "left",
                    padding: "5px 6px", fontSize: 11,
                    color: t.text, background: "transparent", border: "none",
                    cursor: "pointer", borderRadius: 3,
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = t.surfaceOverlay; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                >
                  <span style={{ fontWeight: 500 }}>{s.name}</span>
                  <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>{s.id}</span>
                </button>
              ))}
              {filteredUnpinned.length === 0 && (
                <span style={{ fontSize: 11, color: t.textDim, padding: 4 }}>No matching skills</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Advanced: full skill list */}
      <AdvancedSection title="All Skills">
        <div style={{ paddingTop: 8 }}>
          {editorData.all_skills.length > 6 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 6, marginBottom: 8,
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
              const desc = skill.description?.trim();
              const cleanedDesc = desc && desc !== "---" ? desc : null;
              const sourceType = skill.source_type || "manual";
              const isBotAuthored = sourceType === "tool";
              return (
                <div key={skill.id} style={{
                  padding: "8px 4px", borderRadius: 0,
                  background: isBotAuthored ? "rgba(16,185,129,0.06)" : sel ? t.accentSubtle : "transparent",
                  borderBottom: `1px solid ${isBotAuthored ? "rgba(16,185,129,0.15)" : sel ? t.accentBorder : t.surfaceBorder}`,
                }}>
                  {isBotAuthored ? (
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                      <span style={{
                        display: "inline-flex", alignItems: "center", fontSize: 9, fontWeight: 600,
                        color: "#059669", background: "rgba(16,185,129,0.15)", borderRadius: 3,
                        padding: "2px 5px", marginTop: 1, whiteSpace: "nowrap",
                      }}>
                        auto
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
                          Bot-authored. Auto-injected as on-demand.
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
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", marginTop: 2 }}
                      title={entry?.mode === "pinned" ? "Unpin (switch to on-demand)" : "Pin (full content every turn)"}>
                      <input type="checkbox" checked={entry?.mode === "pinned"}
                        onChange={(e) => {
                          if (e.target.checked) {
                            if (!isSelected(skill.id)) {
                              update({ skills: [...skills, { id: skill.id, mode: "pinned" }] });
                            } else {
                              setMode(skill.id, "pinned");
                            }
                          } else {
                            // Unpin = remove from skills array entirely (auto-enrollment handles on-demand)
                            update({ skills: skills.filter((s) => s.id !== skill.id) });
                          }
                        }}
                        style={{ accentColor: t.accent }} />
                      <Pin size={10} color={entry?.mode === "pinned" ? t.accent : t.textDim} />
                    </label>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, fontWeight: 500, color: entry?.mode === "pinned" ? t.accent : t.text }}>{skill.name}</span>
                        <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{skill.id}</span>
                        {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                        {entry?.mode === "pinned" && (
                          <span style={{ fontSize: 9, fontWeight: 600, color: t.accent, background: t.accentSubtle, padding: "1px 5px", borderRadius: 3 }}>pinned</span>
                        )}
                      </div>
                      {cleanedDesc && (
                        <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {cleanedDesc}
                        </div>
                      )}
                    </div>
                  </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </AdvancedSection>
    </div>
  );
}
