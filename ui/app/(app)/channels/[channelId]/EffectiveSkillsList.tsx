import { useState, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { Plus, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotEditorData, ChannelSettings, EffectiveTools } from "@/src/types/api";

interface Props {
  editorData: BotEditorData;
  settings: ChannelSettings;
  effective: EffectiveTools;
  filter: string;
  onSave: (patch: Partial<ChannelSettings>) => void;
}

const MODE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  pinned: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04" },
  rag: { bg: "rgba(59,130,246,0.10)", fg: "#3b82f6" },
  on_demand: { bg: "rgba(100,100,100,0.10)", fg: "#888" },
};

export function EffectiveSkillsList({ editorData, settings, effective, filter, onSave }: Props) {
  const t = useThemeTokens();
  const q = filter.toLowerCase();

  const [addMode, setAddMode] = useState<string>("on_demand");
  const [addPickerOpen, setAddPickerOpen] = useState(false);

  const skillsDisabled = new Set(settings.skills_disabled || []);
  const skillsExtra = settings.skills_extra || [];
  const skillsExtraIds = new Set(skillsExtra.map((s) => s.id));

  // Effective skills from the API
  const effectiveSkills = effective.skills.filter(
    (s) => !q || s.id.toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q),
  );

  // Skills available to add (from all_skills, not already effective)
  const effectiveIds = new Set(effective.skills.map((s) => s.id));
  const addableSkills = editorData.all_skills.filter(
    (s) => !effectiveIds.has(s.id) && (!q || s.id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)),
  );

  const toggleDisable = useCallback(
    (skillId: string) => {
      const current = settings.skills_disabled || [];
      const next = current.includes(skillId) ? current.filter((s) => s !== skillId) : [...current, skillId];
      onSave({ skills_disabled: next.length ? next : null } as any);
    },
    [settings, onSave],
  );

  const removeExtra = useCallback(
    (skillId: string) => {
      const current = settings.skills_extra || [];
      const next = current.filter((s) => s.id !== skillId);
      onSave({ skills_extra: next.length ? next : null } as any);
    },
    [settings, onSave],
  );

  const addSkill = useCallback(
    (skillId: string) => {
      const current = settings.skills_extra || [];
      const entry = { id: skillId, mode: addMode };
      onSave({ skills_extra: [...current, entry] } as any);
      setAddPickerOpen(false);
    },
    [settings, addMode, onSave],
  );

  return (
    <View style={{ gap: 8 }}>
      {/* Legend */}
      <Text style={{ fontSize: 10, color: t.textDim }}>
        Effective skills after applying bot + workspace + channel layers. Toggle to disable. Use "Add" to include extra
        skills from the global pool.
      </Text>

      {/* Effective skills list */}
      {effectiveSkills.map((skill) => {
        const disabled = skillsDisabled.has(skill.id);
        const isExtra = skillsExtraIds.has(skill.id);
        const modeColors = MODE_BADGE_COLORS[skill.mode] || MODE_BADGE_COLORS.on_demand;

        return (
          <View
            key={skill.id}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              padding: 6,
              paddingHorizontal: 10,
              borderRadius: 6,
              backgroundColor: disabled ? "rgba(239,68,68,0.04)" : t.surface,
              borderWidth: 1,
              borderColor: disabled ? "rgba(239,68,68,0.15)" : t.surfaceRaised,
              opacity: disabled ? 0.6 : 1,
            }}
          >
            <input
              type="checkbox"
              checked={!disabled}
              onChange={() => toggleDisable(skill.id)}
              style={{ accentColor: disabled ? t.danger : t.accent }}
            />
            <View style={{ flex: 1, minWidth: 0 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text
                  style={{
                    fontSize: 12,
                    fontWeight: "500",
                    color: disabled ? t.danger : t.textMuted,
                    textDecorationLine: disabled ? "line-through" : "none",
                  }}
                  numberOfLines={1}
                >
                  {skill.name || skill.id}
                </Text>
                <Text
                  style={{
                    fontSize: 9,
                    paddingHorizontal: 5,
                    paddingVertical: 1,
                    borderRadius: 3,
                    backgroundColor: modeColors.bg,
                    color: modeColors.fg,
                    fontWeight: "600",
                  }}
                >
                  {skill.mode}
                </Text>
                {isExtra && (
                  <Text
                    style={{
                      fontSize: 9,
                      paddingHorizontal: 5,
                      paddingVertical: 1,
                      borderRadius: 3,
                      backgroundColor: "rgba(59,130,246,0.10)",
                      color: "#3b82f6",
                      fontWeight: "600",
                    }}
                  >
                    channel
                  </Text>
                )}
              </View>
              <Text style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>{skill.id}</Text>
            </View>
            {isExtra && (
              <Pressable onPress={() => removeExtra(skill.id)} style={{ padding: 4 }}>
                <X size={12} color={t.danger} />
              </Pressable>
            )}
          </View>
        );
      })}

      {effectiveSkills.length === 0 && (
        <Text style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>No skills configured.</Text>
      )}

      {/* Add skill picker */}
      <View
        style={{
          borderTopWidth: 1,
          borderColor: t.surfaceRaised,
          paddingTop: 10,
          marginTop: 4,
          gap: 8,
        }}
      >
        <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>Add Skill</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <select
            value={addMode}
            onChange={(e: any) => setAddMode(e.target.value)}
            style={{
              background: t.inputBg,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              padding: "4px 8px",
              fontSize: 11,
              color: t.text,
            }}
          >
            <option value="on_demand">on_demand</option>
            <option value="pinned">pinned</option>
            <option value="rag">rag</option>
          </select>
          <Pressable
            onPress={() => setAddPickerOpen(!addPickerOpen)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: 10,
              paddingVertical: 4,
              borderRadius: 4,
              backgroundColor: addableSkills.length ? t.accentSubtle : t.surface,
              borderWidth: 1,
              borderColor: addableSkills.length ? t.accentBorder : t.surfaceRaised,
            }}
          >
            <Plus size={12} color={addableSkills.length ? t.accent : t.textDim} />
            <Text style={{ fontSize: 11, color: addableSkills.length ? t.accent : t.textDim }}>
              {addPickerOpen ? "Cancel" : "Add Skill"}
            </Text>
          </Pressable>
        </View>

        {addPickerOpen && (
          <View
            style={{
              borderWidth: 1,
              borderColor: t.surfaceBorder,
              borderRadius: 6,
              maxHeight: 200,
              overflow: "scroll" as any,
            }}
          >
            {addableSkills.length === 0 ? (
              <Text style={{ padding: 10, fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
                No more skills available to add.
              </Text>
            ) : (
              addableSkills.map((skill) => (
                <Pressable
                  key={skill.id}
                  onPress={() => addSkill(skill.id)}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 8,
                    padding: 8,
                    paddingHorizontal: 10,
                    borderBottomWidth: 1,
                    borderColor: t.surfaceRaised,
                  }}
                >
                  <Plus size={12} color={t.accent} />
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: 12, color: t.textMuted }}>{skill.name}</Text>
                    <Text style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>{skill.id}</Text>
                  </View>
                </Pressable>
              ))
            )}
          </View>
        )}
      </View>
    </View>
  );
}
