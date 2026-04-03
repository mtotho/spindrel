import { useCallback, useMemo } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotEditorData, ChannelSettings, SkillOption } from "@/src/types/api";

interface Props {
  editorData: BotEditorData;
  settings: ChannelSettings;
  filter: string;
  onSave: (patch: Partial<ChannelSettings>) => void;
  isWide: boolean;
  skillFromCarapace: Map<string, { carapaceId: string; carapaceName: string; mode: string }>;
}

function cleanDesc(d: string | null | undefined): string | null {
  if (!d) return null;
  const trimmed = d.trim();
  if (!trimmed || trimmed === "---") return null;
  return trimmed;
}

function SourceBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
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

function CarapaceBadge({ mode, name, t }: { mode: string; name: string; t: any }) {
  return (
    <span style={{
      fontSize: 9, padding: "1px 6px", borderRadius: 3, fontWeight: 500, whiteSpace: "nowrap",
      background: t.purpleSubtle, color: t.purple,
    }}>
      {mode} via {name}
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
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0 2px" }}>
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
  const core: SkillOption[] = [];
  const integrationMap = new Map<string, SkillOption[]>();

  for (const s of skills) {
    const sourceType = s.source_type || "manual";
    if (sourceType === "integration") {
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

  return items;
}

export function EffectiveSkillsList({ editorData, settings, filter, onSave, isWide, skillFromCarapace }: Props) {
  const t = useThemeTokens();

  const extras = settings.skills_extra || [];
  const isExtra = (id: string) => extras.some((s) => s.id === id);
  const getExtra = (id: string) => extras.find((s) => s.id === id);
  const disabledSet = new Set(settings.skills_disabled || []);
  const botSkillIds = new Set((editorData.bot.skills || []).map((s) => s.id));
  const botSkillMap = Object.fromEntries((editorData.bot.skills || []).map((s) => [s.id, s]));

  const toggleExtra = useCallback((id: string) => {
    const wasExtra = extras.some((s) => s.id === id);
    if (wasExtra) {
      const next = extras.filter((s) => s.id !== id);
      onSave({ skills_extra: next.length ? next : null } as any);
    } else {
      const patch: any = { skills_extra: [...extras, { id, mode: "on_demand" }] };
      const currentDisabled = settings.skills_disabled || [];
      if (currentDisabled.includes(id)) {
        const nextDisabled = currentDisabled.filter((s) => s !== id);
        patch.skills_disabled = nextDisabled.length ? nextDisabled : null;
      }
      onSave(patch);
    }
  }, [extras, settings, onSave]);

  const setExtraMode = useCallback((id: string, mode: string) => {
    const next = extras.map((s) =>
      s.id === id ? { ...s, mode, similarity_threshold: mode === "rag" ? s.similarity_threshold : undefined } : s,
    );
    onSave({ skills_extra: next } as any);
  }, [extras, onSave]);

  const toggleDisabled = useCallback((id: string) => {
    const current = settings.skills_disabled || [];
    const isCurrentlyDisabled = current.includes(id);
    const next = isCurrentlyDisabled
      ? current.filter((s) => s !== id)
      : [...current, id];
    const patch: any = { skills_disabled: next.length ? next : null };
    if (!isCurrentlyDisabled && extras.some((s) => s.id === id)) {
      const nextExtras = extras.filter((s) => s.id !== id);
      patch.skills_extra = nextExtras.length ? nextExtras : null;
    }
    onSave(patch);
  }, [settings, extras, onSave]);

  const grouped = useMemo(() => {
    const list = filter
      ? editorData.all_skills.filter((s) =>
          s.id.toLowerCase().includes(filter.toLowerCase()) ||
          s.name.toLowerCase().includes(filter.toLowerCase()) ||
          (s.description || "").toLowerCase().includes(filter.toLowerCase()))
      : editorData.all_skills;
    return groupSkills(list);
  }, [editorData.all_skills, filter]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: isWide ? 0 : 6 }}>
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>
        Check to add skills at the channel level.
        <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#16a34a", fontWeight: 600, marginLeft: 4 }}>bot</span> = already on bot.
      </div>

      {grouped.map((item) => {
        if (item.type === "header") {
          return <SectionHeader key={item.key} label={item.label} count={item.count} />;
        }

        const skill = item.skill;
        const sel = isExtra(skill.id);
        const entry = getExtra(skill.id);
        const onBot = botSkillIds.has(skill.id);
        const botEntry = botSkillMap[skill.id];
        const dis = disabledSet.has(skill.id);
        const desc = cleanDesc(skill.description);
        const carapaceSource = skillFromCarapace.get(skill.id);
        const sourceType = skill.source_type || "manual";

        if (!isWide) {
          return (
            <div key={skill.id} style={{
              display: "flex", flexDirection: "column", gap: 4,
              padding: "10px 12px", background: t.inputBg, borderRadius: 8,
              border: `1px solid ${sel ? t.accentBorder : dis ? "rgba(239,68,68,0.15)" : t.surfaceBorder}`,
              opacity: dis ? 0.6 : 1,
            }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                <input type="checkbox" checked={sel} onChange={() => toggleExtra(skill.id)} style={{ accentColor: t.accent }} />
                <span style={{ fontSize: 13, fontWeight: 500, color: sel ? t.accent : t.text, flex: 1 }}>{skill.name}</span>
                {onBot && (
                  <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#16a34a", fontWeight: 600, whiteSpace: "nowrap" }}>
                    bot{botEntry ? ` \u00b7 ${botEntry.mode}` : ""}
                  </span>
                )}
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 28, flexWrap: "wrap" }}>
                <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textMuted }}>{skill.id}</span>
                {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                {carapaceSource && <CarapaceBadge mode={carapaceSource.mode} name={carapaceSource.carapaceName} t={t} />}
              </div>
              {desc && (
                <div style={{ fontSize: 11, color: t.textDim, marginLeft: 28, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {desc}
                </div>
              )}
              {sel && entry && (
                <div style={{ marginLeft: 28 }}>
                  <select value={entry.mode || "on_demand"} onChange={(e: any) => setExtraMode(skill.id, e.target.value)}
                    style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, color: t.text }}>
                    <option value="on_demand">on_demand</option>
                    <option value="pinned">pinned</option>
                    <option value="rag">rag</option>
                  </select>
                </div>
              )}
            </div>
          );
        }

        return (
          <label
            key={skill.id}
            style={{
              display: "grid", gridTemplateColumns: "24px 160px 1fr auto auto",
              alignItems: "center", gap: 12,
              padding: "6px 4px", background: "transparent",
              borderBottom: `1px solid ${sel ? t.accentBorder : t.surfaceBorder}`,
              cursor: "pointer",
              opacity: dis ? 0.6 : 1,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = t.inputBg; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
          >
            <input type="checkbox" checked={sel} onChange={() => toggleExtra(skill.id)} style={{ accentColor: t.accent }} />
            <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {skill.id}
            </span>
            <div style={{ overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: sel ? t.accent : t.text }}>{skill.name}</span>
                {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                {carapaceSource && <CarapaceBadge mode={carapaceSource.mode} name={carapaceSource.carapaceName} t={t} />}
              </div>
              {desc && (
                <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
                  {desc}
                </div>
              )}
            </div>
            {onBot ? (
              <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#16a34a", fontWeight: 600, whiteSpace: "nowrap" }}>
                bot{botEntry ? ` \u00b7 ${botEntry.mode}` : ""}
              </span>
            ) : <span />}
            {sel && entry ? (
              <select
                value={entry.mode || "on_demand"}
                onChange={(e: any) => setExtraMode(skill.id, e.target.value)}
                onClick={(e) => e.stopPropagation()}
                style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, color: t.text }}
              >
                <option value="on_demand">on_demand</option>
                <option value="pinned">pinned</option>
                <option value="rag">rag</option>
              </select>
            ) : <span />}
          </label>
        );
      })}

      {/* Disable bot skills */}
      {(editorData.bot.skills || []).length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0 4px" }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1 }}>
              Disable bot skills
            </span>
            <span style={{ fontSize: 10, color: t.textDim }}>
              {(editorData.bot.skills || []).length}
            </span>
            <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: isWide ? 0 : 6 }}>
            {(editorData.bot.skills || []).map((bs) => {
              const skill = editorData.all_skills.find((s) => s.id === bs.id);
              const dis = disabledSet.has(bs.id);

              if (!isWide) {
                return (
                  <label key={bs.id} style={{
                    display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
                    padding: "8px 12px", background: t.inputBg, borderRadius: 8,
                    border: `1px solid ${dis ? "rgba(239,68,68,0.15)" : t.surfaceBorder}`,
                  }}>
                    <input type="checkbox" checked={dis} onChange={() => toggleDisabled(bs.id)} style={{ accentColor: t.danger }} />
                    <span style={{
                      fontSize: 13, fontWeight: 500, flex: 1,
                      color: dis ? t.danger : t.text,
                      textDecoration: dis ? "line-through" : "none",
                    }}>{skill?.name || bs.id}</span>
                    <span style={{ fontSize: 10, color: t.textMuted, fontFamily: "monospace" }}>{bs.mode}</span>
                  </label>
                );
              }

              return (
                <label
                  key={bs.id}
                  style={{
                    display: "grid", gridTemplateColumns: "24px 160px 1fr auto",
                    alignItems: "center", gap: 12,
                    padding: "6px 4px", background: "transparent",
                    borderBottom: `1px solid ${t.surfaceBorder}`,
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = t.inputBg; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  <input type="checkbox" checked={dis} onChange={() => toggleDisabled(bs.id)} style={{ accentColor: t.danger }} />
                  <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {bs.id}
                  </span>
                  <span style={{
                    fontSize: 13, fontWeight: 500,
                    color: dis ? t.danger : t.text,
                    textDecoration: dis ? "line-through" : "none",
                  }}>
                    {skill?.name || bs.id}
                  </span>
                  <span style={{ fontSize: 10, color: t.textMuted, fontFamily: "monospace" }}>{bs.mode}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
