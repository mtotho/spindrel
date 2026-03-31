import { useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator, TextInput, ScrollView, Alert, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  useCarapace,
  useCreateCarapace,
  useUpdateCarapace,
  useDeleteCarapace,
  useResolveCarapace,
} from "@/src/api/hooks/useCarapaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Save, Trash2, ArrowLeft, ChevronDown, ChevronRight, Layers } from "lucide-react";
import type { Carapace, SkillConfig } from "@/src/types/api";

export default function CarapaceDetailPage() {
  const tokens = useThemeTokens();
  const router = useRouter();
  const { carapaceId } = useLocalSearchParams<{ carapaceId: string }>();
  const isNew = carapaceId === "new";

  const { data: existing, isLoading } = useCarapace(isNew ? undefined : carapaceId);
  const { data: resolved } = useResolveCarapace(isNew ? undefined : carapaceId);
  const createMut = useCreateCarapace();
  const updateMut = useUpdateCarapace(carapaceId || "");
  const deleteMut = useDeleteCarapace();

  const [draft, setDraft] = useState<Partial<Carapace>>({
    id: "",
    name: "",
    description: "",
    skills: [],
    local_tools: [],
    mcp_tools: [],
    pinned_tools: [],
    system_prompt_fragment: "",
    includes: [],
    tags: [],
  });
  const [dirty, setDirty] = useState(false);
  const [showResolved, setShowResolved] = useState(false);

  useEffect(() => {
    if (existing && !isNew) {
      setDraft({
        id: existing.id,
        name: existing.name,
        description: existing.description || "",
        skills: existing.skills || [],
        local_tools: existing.local_tools || [],
        mcp_tools: existing.mcp_tools || [],
        pinned_tools: existing.pinned_tools || [],
        system_prompt_fragment: existing.system_prompt_fragment || "",
        includes: existing.includes || [],
        tags: existing.tags || [],
      });
    }
  }, [existing, isNew]);

  const update = useCallback((patch: Partial<Carapace>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  }, []);

  const handleSave = async () => {
    try {
      if (isNew) {
        await createMut.mutateAsync({
          id: draft.id || "",
          name: draft.name || "",
          description: draft.description || undefined,
          skills: draft.skills || [],
          local_tools: draft.local_tools || [],
          mcp_tools: draft.mcp_tools || [],
          pinned_tools: draft.pinned_tools || [],
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes || [],
          tags: draft.tags || [],
        });
        router.back();
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || undefined,
          skills: draft.skills,
          local_tools: draft.local_tools,
          mcp_tools: draft.mcp_tools,
          pinned_tools: draft.pinned_tools,
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes,
          tags: draft.tags,
        });
        setDirty(false);
      }
    } catch {
      // error handled by mutation
    }
  };

  const handleDelete = () => {
    const doDelete = async () => {
      try {
        await deleteMut.mutateAsync(carapaceId!);
        router.back();
      } catch {
        // error shown via mutation state below
      }
    };
    if (Platform.OS === "web") {
      if (window.confirm(`Delete carapace "${draft.name}"?`)) doDelete();
    } else {
      Alert.alert("Delete Carapace", `Delete "${draft.name}"?`, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: doDelete },
      ]);
    }
  };

  const isFileBased = existing?.source_type === "file" || existing?.source_type === "integration";

  if (!isNew && isLoading) {
    return <ActivityIndicator style={{ marginTop: 60 }} />;
  }

  const hasIncludes = (draft.includes || []).length > 0;

  return (
    <ScrollView style={{ flex: 1 }}>
      <MobileHeader title={isNew ? "New Carapace" : draft.name || "Carapace"} />
      <View style={{ padding: 16, maxWidth: 720 }}>
        {/* Top actions */}
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <Pressable onPress={() => router.back()} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <ArrowLeft size={16} color={tokens.textMuted} />
            <Text style={{ color: tokens.textMuted, fontSize: 13 }}>Back</Text>
          </Pressable>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {!isNew && !isFileBased && (
              <Pressable onPress={handleDelete} style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: "rgba(239,68,68,0.1)" }}>
                <Trash2 size={14} color="#ef4444" />
                <Text style={{ color: "#ef4444", fontSize: 12 }}>Delete</Text>
              </Pressable>
            )}
            {!isFileBased && (
              <Pressable
                onPress={handleSave}
                disabled={!dirty && !isNew}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: dirty || isNew ? tokens.accent : tokens.surfaceBorder,
                  opacity: dirty || isNew ? 1 : 0.5,
                }}
              >
                <Save size={14} color="#fff" />
                <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                  {isNew ? "Create" : "Save"}
                </Text>
              </Pressable>
            )}
          </View>
        </View>

        {(createMut.isError || updateMut.isError || deleteMut.isError) && (
          <View style={{ backgroundColor: "rgba(239,68,68,0.08)", padding: 10, borderRadius: 8, marginBottom: 12 }}>
            <Text style={{ color: "#ef4444", fontSize: 12 }}>
              {(createMut.error || updateMut.error || deleteMut.error)?.message || "Operation failed"}
            </Text>
          </View>
        )}

        {isFileBased && (
          <View style={{ backgroundColor: "rgba(59,130,246,0.08)", padding: 10, borderRadius: 8, marginBottom: 16 }}>
            <Text style={{ color: "#3b82f6", fontSize: 12 }}>
              This carapace is managed by a file ({existing?.source_path}). Edit the file to make changes.
            </Text>
          </View>
        )}

        {/* ID (only for new) */}
        {isNew && (
          <FieldRow label="ID" tokens={tokens}>
            <TextInput
              value={draft.id || ""}
              onChangeText={(v) => update({ id: v.toLowerCase().replace(/\s+/g, "-") })}
              placeholder="e.g. qa-expert"
              placeholderTextColor={tokens.textMuted}
              style={inputStyle(tokens)}
            />
          </FieldRow>
        )}

        <FieldRow label="Name" tokens={tokens}>
          <TextInput
            value={draft.name || ""}
            onChangeText={(v) => update({ name: v })}
            placeholder="Display name"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="Description" tokens={tokens}>
          <TextInput
            value={draft.description || ""}
            onChangeText={(v) => update({ description: v })}
            placeholder="Short description"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="Tags" tokens={tokens} hint="Comma-separated">
          <TextInput
            value={(draft.tags || []).join(", ")}
            onChangeText={(v) => update({ tags: v.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="testing, quality"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="Skills" tokens={tokens} hint="Comma-separated skill IDs. Prefix with * for pinned mode (e.g. *workspace-orchestrator, channel-workspace)">
          <TextInput
            value={skillsToString(draft.skills || [])}
            onChangeText={(v) => update({ skills: parseSkillsString(v) })}
            placeholder="*pinned-skill, on-demand-skill"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
          {(draft.skills || []).length > 0 && (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
              {(draft.skills || []).map((s: SkillConfig) => (
                <View
                  key={s.id}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 4,
                    backgroundColor: s.mode === "pinned" ? "rgba(59,130,246,0.1)" : "rgba(168,85,247,0.08)",
                    paddingHorizontal: 6,
                    paddingVertical: 2,
                    borderRadius: 4,
                  }}
                >
                  <Text style={{ fontSize: 11, color: s.mode === "pinned" ? "#3b82f6" : "#9333ea" }}>
                    {s.id}
                  </Text>
                  <Text style={{ fontSize: 9, color: tokens.textDim }}>{s.mode || "on_demand"}</Text>
                </View>
              ))}
            </View>
          )}
        </FieldRow>

        <FieldRow label="Local Tools" tokens={tokens} hint="Comma-separated tool names">
          <TextInput
            value={(draft.local_tools || []).join(", ")}
            onChangeText={(v) => update({ local_tools: v.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="exec_command, file, web_search"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="Pinned Tools" tokens={tokens} hint="Tools that bypass RAG">
          <TextInput
            value={(draft.pinned_tools || []).join(", ")}
            onChangeText={(v) => update({ pinned_tools: v.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="exec_command"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="MCP Tools" tokens={tokens} hint="MCP server names">
          <TextInput
            value={(draft.mcp_tools || []).join(", ")}
            onChangeText={(v) => update({ mcp_tools: v.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="homeassistant, github"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="Includes" tokens={tokens} hint="Other carapace IDs to compose with">
          <TextInput
            value={(draft.includes || []).join(", ")}
            onChangeText={(v) => update({ includes: v.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="code-review, testing"
            placeholderTextColor={tokens.textMuted}
            style={inputStyle(tokens)}
            editable={!isFileBased}
          />
        </FieldRow>

        <FieldRow label="System Prompt Fragment" tokens={tokens} hint="Behavioral instructions injected when active">
          <TextInput
            value={draft.system_prompt_fragment || ""}
            onChangeText={(v) => update({ system_prompt_fragment: v })}
            placeholder="## Expert Mode\n\nFollow this workflow..."
            placeholderTextColor={tokens.textMuted}
            style={[inputStyle(tokens), { height: 160, textAlignVertical: "top" }]}
            multiline
            editable={!isFileBased}
          />
        </FieldRow>

        {/* Resolved Preview — only for existing carapaces with includes */}
        {!isNew && resolved && (hasIncludes || resolved.local_tools.length > 0) && (
          <View style={{ marginTop: 8 }}>
            <Pressable
              onPress={() => setShowResolved(!showResolved)}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                paddingVertical: 8,
              }}
            >
              {showResolved ? (
                <ChevronDown size={14} color={tokens.textMuted} />
              ) : (
                <ChevronRight size={14} color={tokens.textMuted} />
              )}
              <Layers size={14} color={tokens.accent} />
              <Text style={{ color: tokens.text, fontSize: 13, fontWeight: "600" }}>
                Resolved Preview
              </Text>
              {hasIncludes && (
                <Text style={{ color: tokens.textDim, fontSize: 11 }}>
                  ({resolved.resolved_ids.length} carapace{resolved.resolved_ids.length !== 1 ? "s" : ""})
                </Text>
              )}
            </Pressable>

            {showResolved && (
              <View style={{
                backgroundColor: tokens.surface,
                borderWidth: 1,
                borderColor: tokens.surfaceBorder,
                borderRadius: 8,
                padding: 12,
                gap: 10,
              }}>
                {resolved.resolved_ids.length > 1 && (
                  <PreviewRow label="Includes chain" tokens={tokens}>
                    <Text style={{ fontSize: 11, color: tokens.textMuted, fontFamily: "monospace" }}>
                      {resolved.resolved_ids.join(" → ")}
                    </Text>
                  </PreviewRow>
                )}
                <PreviewRow label="Tools" tokens={tokens}>
                  <TagList items={resolved.local_tools} color="#22c55e" tokens={tokens} />
                </PreviewRow>
                {resolved.mcp_tools.length > 0 && (
                  <PreviewRow label="MCP" tokens={tokens}>
                    <TagList items={resolved.mcp_tools} color="#06b6d4" tokens={tokens} />
                  </PreviewRow>
                )}
                <PreviewRow label="Pinned" tokens={tokens}>
                  <TagList items={resolved.pinned_tools} color="#f97316" tokens={tokens} />
                </PreviewRow>
                <PreviewRow label="Skills" tokens={tokens}>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
                    {resolved.skills.map((s) => (
                      <View
                        key={s.id}
                        style={{
                          flexDirection: "row",
                          gap: 3,
                          backgroundColor: s.mode === "pinned" ? "rgba(59,130,246,0.1)" : "rgba(168,85,247,0.08)",
                          paddingHorizontal: 5,
                          paddingVertical: 1,
                          borderRadius: 3,
                        }}
                      >
                        <Text style={{ fontSize: 10, color: s.mode === "pinned" ? "#3b82f6" : "#9333ea" }}>
                          {s.id}
                        </Text>
                        <Text style={{ fontSize: 9, color: tokens.textDim }}>{s.mode}</Text>
                      </View>
                    ))}
                    {resolved.skills.length === 0 && (
                      <Text style={{ fontSize: 11, color: tokens.textDim }}>none</Text>
                    )}
                  </View>
                </PreviewRow>
                <PreviewRow label="Fragments" tokens={tokens}>
                  <Text style={{ fontSize: 11, color: tokens.textMuted }}>
                    {resolved.system_prompt_fragments.length} fragment{resolved.system_prompt_fragments.length !== 1 ? "s" : ""},{" "}
                    {resolved.system_prompt_fragments.reduce((a, f) => a + f.length, 0)} chars
                  </Text>
                </PreviewRow>
              </View>
            )}
          </View>
        )}
      </View>
    </ScrollView>
  );
}

function FieldRow({
  label,
  hint,
  tokens,
  children,
}: {
  label: string;
  hint?: string;
  tokens: ReturnType<typeof useThemeTokens>;
  children: React.ReactNode;
}) {
  return (
    <View style={{ marginBottom: 14 }}>
      <Text style={{ color: tokens.text, fontSize: 13, fontWeight: "600", marginBottom: 4 }}>{label}</Text>
      {hint && <Text style={{ color: tokens.textMuted, fontSize: 11, marginBottom: 4 }}>{hint}</Text>}
      {children}
    </View>
  );
}

function PreviewRow({
  label,
  tokens,
  children,
}: {
  label: string;
  tokens: ReturnType<typeof useThemeTokens>;
  children: React.ReactNode;
}) {
  return (
    <View style={{ gap: 3 }}>
      <Text style={{ fontSize: 11, fontWeight: "600", color: tokens.textDim }}>{label}</Text>
      {children}
    </View>
  );
}

function TagList({ items, color, tokens }: { items: string[]; color: string; tokens: ReturnType<typeof useThemeTokens> }) {
  if (items.length === 0) {
    return <Text style={{ fontSize: 11, color: tokens.textDim }}>none</Text>;
  }
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
      {items.map((item) => (
        <View key={item} style={{ backgroundColor: `${color}15`, paddingHorizontal: 5, paddingVertical: 1, borderRadius: 3 }}>
          <Text style={{ fontSize: 10, color }}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

function inputStyle(tokens: ReturnType<typeof useThemeTokens>) {
  return {
    backgroundColor: tokens.surface,
    borderWidth: 1,
    borderColor: tokens.surfaceBorder,
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 8,
    color: tokens.text,
    fontSize: 13,
  } as const;
}

/** Convert skills array to editable string: *pinned-skill, on-demand-skill */
function skillsToString(skills: SkillConfig[]): string {
  return skills
    .map((s) => (s.mode === "pinned" ? `*${s.id}` : s.id))
    .join(", ");
}

/** Parse skills string back to SkillConfig[]: *pinned-skill → {id, mode: "pinned"} */
function parseSkillsString(input: string): SkillConfig[] {
  return input
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => {
      if (s.startsWith("*")) {
        return { id: s.slice(1), mode: "pinned" };
      }
      return { id: s, mode: "on_demand" };
    });
}
