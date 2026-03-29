import { useCallback } from "react";
import { View, Text } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotEditorData, ChannelSettings } from "@/src/types/api";

interface Props {
  editorData: BotEditorData;
  settings: ChannelSettings;
  filter: string;
  onSave: (patch: Partial<ChannelSettings>) => void;
}

export function EffectiveSkillsList({ editorData, settings, filter, onSave }: Props) {
  const t = useThemeTokens();

  // Channel-level additions
  const extras = settings.skills_extra || [];
  const isExtra = (id: string) => extras.some((s) => s.id === id);
  const getExtra = (id: string) => extras.find((s) => s.id === id);

  // Channel-level disabled
  const disabledSet = new Set(settings.skills_disabled || []);

  // Bot's configured skills
  const botSkillIds = new Set((editorData.bot.skills || []).map((s) => s.id));
  const botSkillMap = Object.fromEntries((editorData.bot.skills || []).map((s) => [s.id, s]));

  const toggleExtra = useCallback((id: string) => {
    const wasExtra = extras.some((s) => s.id === id);
    if (wasExtra) {
      const next = extras.filter((s) => s.id !== id);
      onSave({ skills_extra: next.length ? next : null } as any);
    } else {
      // Also remove from disabled if it was disabled
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
    // If disabling, also remove from extras if present
    if (!isCurrentlyDisabled && extras.some((s) => s.id === id)) {
      const nextExtras = extras.filter((s) => s.id !== id);
      patch.skills_extra = nextExtras.length ? nextExtras : null;
    }
    onSave(patch);
  }, [settings, extras, onSave]);

  const filtered = filter
    ? editorData.all_skills.filter((s) =>
        s.id.toLowerCase().includes(filter.toLowerCase()) ||
        s.name.toLowerCase().includes(filter.toLowerCase()) ||
        (s.description || "").toLowerCase().includes(filter.toLowerCase()))
    : editorData.all_skills;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Channel additions — mirrors bot SkillsSection */}
      <div style={{ fontSize: 11, color: t.textDim }}>
        Check skills to <strong style={{ color: t.textMuted }}>add at the channel level</strong>, independent of the bot's config.
        The <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 3, background: "rgba(34,197,94,0.12)", color: "#16a34a", fontWeight: 600 }}>bot</span> badge shows skills the bot already has.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 6 }}>
        {filtered.map((skill) => {
          const sel = isExtra(skill.id);
          const entry = getExtra(skill.id);
          const onBot = botSkillIds.has(skill.id);
          const botEntry = botSkillMap[skill.id];
          const disabled = disabledSet.has(skill.id);

          return (
            <div key={skill.id} style={{
              padding: 8, borderRadius: 6,
              background: sel ? t.accentSubtle : disabled ? "rgba(239,68,68,0.04)" : t.surface,
              border: `1px solid ${sel ? t.accentBorder : disabled ? "rgba(239,68,68,0.15)" : t.surfaceRaised}`,
              opacity: disabled ? 0.6 : 1,
            }}>
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={sel} onChange={() => toggleExtra(skill.id)} style={{ accentColor: t.accent, marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: sel ? t.accent : t.textMuted }}>{skill.name}</span>
                    <span style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>{skill.id}</span>
                    {onBot && (
                      <span style={{
                        fontSize: 9, padding: "1px 4px", borderRadius: 3,
                        background: "rgba(34,197,94,0.12)", color: "#16a34a", fontWeight: 600,
                      }}>
                        bot{botEntry ? ` · ${botEntry.mode}` : ""}
                      </span>
                    )}
                  </div>
                  {skill.description && (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {skill.description}
                    </div>
                  )}
                </div>
              </label>
              {sel && entry && (
                <div style={{ marginTop: 6, marginLeft: 22 }}>
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
        })}
      </div>

      {/* Disabled bot skills */}
      {(editorData.bot.skills || []).length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>
            Disable bot skills
          </div>
          <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>
            Check to <strong style={{ color: t.danger }}>disable</strong> a skill the bot has for this channel.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
            {(editorData.bot.skills || []).map((bs) => {
              const skill = editorData.all_skills.find((s) => s.id === bs.id);
              const dis = disabledSet.has(bs.id);
              return (
                <label key={bs.id} style={{
                  display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
                  padding: "4px 8px", borderRadius: 4,
                  background: dis ? "rgba(239,68,68,0.06)" : "transparent",
                  border: `1px solid ${dis ? "rgba(239,68,68,0.15)" : "transparent"}`,
                }}>
                  <input type="checkbox" checked={dis} onChange={() => toggleDisabled(bs.id)}
                    style={{ accentColor: t.danger }} />
                  <span style={{
                    fontSize: 11, color: dis ? t.danger : t.textDim,
                    textDecoration: dis ? "line-through" : "none",
                  }}>{skill?.name || bs.id}</span>
                  <span style={{ fontSize: 9, color: t.surfaceBorder }}>{bs.mode}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
