import { useState, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Check, Search, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannelEffectiveTools,
} from "@/src/api/hooks/useChannels";
import { useBotEditorData } from "@/src/api/hooks/useBots";
import { Section, SelectInput, EmptyState } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Mode options
// ---------------------------------------------------------------------------
type OverrideMode = "inherit" | "override" | "disabled";

const MODE_OPTIONS = [
  { label: "Inherit from bot", value: "inherit" },
  { label: "Override (whitelist)", value: "override" },
  { label: "Disable (blacklist)", value: "disabled" },
];

// ---------------------------------------------------------------------------
// Tools Override Tab
// ---------------------------------------------------------------------------
export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
  const updateMutation = useUpdateChannelSettings(channelId);
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);

  // Derive current modes from settings
  const getMode = (overrideKey: string, disabledKey: string): OverrideMode => {
    if (!settings) return "inherit";
    const o = (settings as any)[overrideKey];
    const d = (settings as any)[disabledKey];
    if (o != null) return "override";
    if (d != null) return "disabled";
    return "inherit";
  };

  const localMode = getMode("local_tools_override", "local_tools_disabled");
  const mcpMode = getMode("mcp_servers_override", "mcp_servers_disabled");
  const clientMode = getMode("client_tools_override", "client_tools_disabled");

  // Get the list being edited for a category
  const getEditList = (mode: OverrideMode, overrideKey: string, disabledKey: string): string[] => {
    if (!settings) return [];
    if (mode === "override") return (settings as any)[overrideKey] || [];
    if (mode === "disabled") return (settings as any)[disabledKey] || [];
    return [];
  };

  const localList = getEditList(localMode, "local_tools_override", "local_tools_disabled");
  const mcpList = getEditList(mcpMode, "mcp_servers_override", "mcp_servers_disabled");
  const clientList = getEditList(clientMode, "client_tools_override", "client_tools_disabled");

  // Save helper
  const save = useCallback(async (patch: Partial<ChannelSettings>) => {
    setSaved(false);
    await updateMutation.mutateAsync(patch);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }, [updateMutation]);

  // Mode change handler
  const handleModeChange = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    newMode: OverrideMode,
  ) => {
    const overrideKey = `${category}_override` as keyof ChannelSettings;
    const disabledKey = `${category}_disabled` as keyof ChannelSettings;
    const patch: any = {};
    if (newMode === "inherit") {
      patch[overrideKey] = null;
      patch[disabledKey] = null;
    } else if (newMode === "override") {
      patch[overrideKey] = [];
      patch[disabledKey] = null;
    } else {
      patch[overrideKey] = null;
      patch[disabledKey] = [];
    }
    save(patch);
  }, [save]);

  // Toggle a tool in override/disabled list
  const toggleTool = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    mode: OverrideMode,
    currentList: string[],
    toolName: string,
  ) => {
    if (mode === "inherit") return;
    const key = mode === "override" ? `${category}_override` : `${category}_disabled`;
    const next = currentList.includes(toolName)
      ? currentList.filter((t) => t !== toolName)
      : [...currentList, toolName];
    save({ [key]: next } as any);
  }, [save]);

  // Toggle all tools in a group
  const toggleGroup = useCallback((
    category: "local_tools" | "mcp_servers" | "client_tools",
    mode: OverrideMode,
    currentList: string[],
    toolNames: string[],
  ) => {
    if (mode === "inherit") return;
    const key = mode === "override" ? `${category}_override` : `${category}_disabled`;
    const allIn = toolNames.every((n) => currentList.includes(n));
    const next = allIn
      ? currentList.filter((t) => !toolNames.includes(t))
      : [...new Set([...currentList, ...toolNames])];
    save({ [key]: next } as any);
  }, [save]);

  if (editorLoading) {
    return <ActivityIndicator size="small" color={t.textDim} />;
  }

  if (!editorData) {
    return <EmptyState message="No bot editor data available" />;
  }

  const q = filter.toLowerCase();

  // Get all bot tool names for reference
  const allBotLocalTools = editorData.tool_groups.flatMap((g) =>
    g.packs.flatMap((p) => p.tools.map((t) => t.name))
  );

  return (
    <>
      {/* Status indicator */}
      {saved && (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <Check size={12} color="#22c55e" />
          <Text style={{ color: "#22c55e", fontSize: 11 }}>Saved</Text>
        </View>
      )}

      {/* Search */}
      <View style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
        background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "5px 10px",
        marginBottom: 12,
      } as any}>
        <Search size={12} color={t.textDim} />
        <input
          type="text" value={filter}
          onChange={(e: any) => setFilter(e.target.value)}
          placeholder="Search tools..."
          style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
        />
        {filter && (
          <Pressable onPress={() => setFilter("")}>
            <X size={10} color={t.textDim} />
          </Pressable>
        )}
      </View>

      {/* Legend */}
      <View style={{ flexDirection: "row", gap: 16, marginBottom: 16 }}>
        <Text style={{ fontSize: 10, color: t.textDim }}>
          Inherit = use bot defaults | Override = only checked tools active | Disable = checked tools removed
        </Text>
      </View>

      {/* Local Tools */}
      <Section title="Local Tools">
        <View style={{ marginBottom: 8 }}>
          <SelectInput
            value={localMode}
            onChange={(v: string) => handleModeChange("local_tools", v as OverrideMode)}
            options={MODE_OPTIONS}
          />
        </View>
        {localMode === "inherit" ? (
          <Text style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
            Using bot defaults ({allBotLocalTools.length} tools)
          </Text>
        ) : (
          <>
            <Text style={{ fontSize: 10, color: t.textDim, marginBottom: 8 }}>
              {localMode === "override"
                ? `Checked tools will be active (${localList.length} selected)`
                : `Checked tools will be disabled (${localList.length} disabled)`}
            </Text>
            {editorData.tool_groups.map((group) => {
              const groupTools = group.packs.flatMap((p) => p.tools.map((t) => t.name));
              const filteredPacks = group.packs.map((pack) => ({
                ...pack,
                tools: q ? pack.tools.filter((t) => t.name.toLowerCase().includes(q)) : pack.tools,
              })).filter((p) => p.tools.length > 0);
              if (filteredPacks.length === 0) return null;

              const groupFilteredTools = filteredPacks.flatMap((p) => p.tools.map((t) => t.name));
              const selectedInGroup = groupTools.filter((n) => localList.includes(n)).length;
              const allInGroup = selectedInGroup === groupTools.length && groupTools.length > 0;

              return (
                <View key={group.integration} style={{
                  borderWidth: 1, borderColor: t.surfaceRaised, borderRadius: 8, overflow: "hidden", marginBottom: 8,
                }}>
                  {/* Group header */}
                  <View style={{
                    padding: 6, paddingHorizontal: 10, backgroundColor: t.surface,
                    flexDirection: "row", alignItems: "center", gap: 6,
                  }}>
                    {group.is_core ? (
                      <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>Core</Text>
                    ) : (
                      <Text style={{
                        fontSize: 9, fontWeight: "700", paddingHorizontal: 5, paddingVertical: 1,
                        borderRadius: 3, backgroundColor: "#92400e33", color: "#d97706",
                        textTransform: "uppercase",
                      }}>{group.integration}</Text>
                    )}
                    <Text style={{ fontSize: 9, color: t.textDim, marginLeft: "auto" }}>
                      {selectedInGroup}/{groupTools.length}
                    </Text>
                    <Pressable
                      onPress={() => toggleGroup("local_tools", localMode, localList, groupTools)}
                    >
                      <Text style={{
                        fontSize: 9, paddingHorizontal: 6, paddingVertical: 1,
                        borderWidth: 1, borderColor: t.surfaceBorder, borderRadius: 4,
                        color: allInGroup ? "#f87171" : "#16a34a",
                      }}>{allInGroup ? "none" : "all"}</Text>
                    </Pressable>
                  </View>

                  {/* Tools grid */}
                  <View style={{ flexDirection: "row", flexWrap: "wrap", padding: 4, gap: 1 }}>
                    {filteredPacks.flatMap((pack) =>
                      pack.tools.map((tool) => {
                        const checked = localList.includes(tool.name);
                        return (
                          <Pressable
                            key={tool.name}
                            onPress={() => toggleTool("local_tools", localMode, localList, tool.name)}
                            style={{
                              flexDirection: "row", alignItems: "center", gap: 4,
                              padding: 3, paddingHorizontal: 6, borderRadius: 3,
                              width: "49%",
                              backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                              borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                            }}
                          >
                            <input
                              type="checkbox" checked={checked} readOnly
                              style={{ accentColor: localMode === "disabled" ? "#ef4444" : t.accent }}
                            />
                            <Text style={{
                              fontFamily: "monospace", fontSize: 11,
                              color: checked ? (localMode === "disabled" ? "#dc2626" : "#2563eb") : t.textDim,
                            }} numberOfLines={1}>{tool.name}</Text>
                          </Pressable>
                        );
                      })
                    )}
                  </View>
                </View>
              );
            })}
          </>
        )}
      </Section>

      {/* MCP Servers */}
      {editorData.mcp_servers.length > 0 && (
        <Section title="MCP Servers">
          <View style={{ marginBottom: 8 }}>
            <SelectInput
              value={mcpMode}
              onChange={(v: string) => handleModeChange("mcp_servers", v as OverrideMode)}
              options={MODE_OPTIONS}
            />
          </View>
          {mcpMode === "inherit" ? (
            <Text style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
              Using bot defaults
            </Text>
          ) : (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
              {editorData.mcp_servers.filter((s) => !q || s.toLowerCase().includes(q)).map((srv) => {
                const checked = mcpList.includes(srv);
                return (
                  <Pressable
                    key={srv}
                    onPress={() => toggleTool("mcp_servers", mcpMode, mcpList, srv)}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 6,
                      padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                      backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                      borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                    }}
                  >
                    <input
                      type="checkbox" checked={checked} readOnly
                      style={{ accentColor: mcpMode === "disabled" ? "#ef4444" : t.accent }}
                    />
                    <Text style={{
                      fontFamily: "monospace", fontSize: 11,
                      color: checked ? (mcpMode === "disabled" ? "#dc2626" : "#2563eb") : t.textDim,
                    }}>{srv}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </Section>
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <Section title="Client Tools">
          <View style={{ marginBottom: 8 }}>
            <SelectInput
              value={clientMode}
              onChange={(v: string) => handleModeChange("client_tools", v as OverrideMode)}
              options={MODE_OPTIONS}
            />
          </View>
          {clientMode === "inherit" ? (
            <Text style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
              Using bot defaults
            </Text>
          ) : (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
              {editorData.client_tools.filter((t) => !q || t.toLowerCase().includes(q)).map((tool) => {
                const checked = clientList.includes(tool);
                return (
                  <Pressable
                    key={tool}
                    onPress={() => toggleTool("client_tools", clientMode, clientList, tool)}
                    style={{
                      flexDirection: "row", alignItems: "center", gap: 6,
                      padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                      backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                      borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                    }}
                  >
                    <input
                      type="checkbox" checked={checked} readOnly
                      style={{ accentColor: clientMode === "disabled" ? "#ef4444" : t.accent }}
                    />
                    <Text style={{
                      fontFamily: "monospace", fontSize: 11,
                      color: checked ? (clientMode === "disabled" ? "#dc2626" : "#2563eb") : t.textDim,
                    }}>{tool}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </Section>
      )}

      {/* Skills */}
      {editorData.all_skills.length > 0 && (() => {
        const skillMode = getMode("skills_override", "skills_disabled");
        // For override: list of {id, mode?, similarity_threshold?} dicts
        const skillOverrideList: { id: string; mode?: string }[] = settings?.skills_override || [];
        const skillOverrideIds = skillOverrideList.map((s) => s.id);
        // For disabled: list of skill id strings
        const skillDisabledList: string[] = settings?.skills_disabled || [];
        // Bot's configured skills
        const botSkillIds = (editorData.bot.skills || []).map((s: any) => s.id);
        // All available skills (from all_skills), filtered to bot's skills
        const botSkills = editorData.all_skills.filter((s) => botSkillIds.includes(s.id));

        const handleSkillModeChange = (newMode: OverrideMode) => {
          const patch: any = {};
          if (newMode === "inherit") {
            patch.skills_override = null;
            patch.skills_disabled = null;
          } else if (newMode === "override") {
            patch.skills_override = [];
            patch.skills_disabled = null;
          } else {
            patch.skills_override = null;
            patch.skills_disabled = [];
          }
          save(patch);
        };

        const toggleSkill = (skillId: string) => {
          if (skillMode === "override") {
            const next = skillOverrideIds.includes(skillId)
              ? skillOverrideList.filter((s) => s.id !== skillId)
              : [...skillOverrideList, { id: skillId }];
            save({ skills_override: next } as any);
          } else if (skillMode === "disabled") {
            const next = skillDisabledList.includes(skillId)
              ? skillDisabledList.filter((s) => s !== skillId)
              : [...skillDisabledList, skillId];
            save({ skills_disabled: next } as any);
          }
        };

        const toggleAllSkills = () => {
          const ids = botSkills.map((s) => s.id);
          if (skillMode === "override") {
            const allIn = ids.every((id) => skillOverrideIds.includes(id));
            const next = allIn ? [] : ids.map((id) => ({ id }));
            save({ skills_override: next } as any);
          } else if (skillMode === "disabled") {
            const allIn = ids.every((id) => skillDisabledList.includes(id));
            const next = allIn ? [] : ids;
            save({ skills_disabled: next } as any);
          }
        };

        return (
          <Section title="Skills">
            <View style={{ marginBottom: 8 }}>
              <SelectInput
                value={skillMode}
                onChange={(v: string) => handleSkillModeChange(v as OverrideMode)}
                options={MODE_OPTIONS}
              />
            </View>
            {skillMode === "inherit" ? (
              <Text style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
                Using bot defaults ({botSkills.length} skills)
              </Text>
            ) : (
              <>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <Text style={{ fontSize: 10, color: t.textDim, flex: 1 }}>
                    {skillMode === "override"
                      ? `Checked skills will be active (${skillOverrideIds.length} selected)`
                      : `Checked skills will be disabled (${skillDisabledList.length} disabled)`}
                  </Text>
                  <Pressable onPress={toggleAllSkills}>
                    <Text style={{
                      fontSize: 9, paddingHorizontal: 6, paddingVertical: 1,
                      borderWidth: 1, borderColor: t.surfaceBorder, borderRadius: 4,
                      color: "#16a34a",
                    }}>
                      {(skillMode === "override"
                        ? botSkills.every((s) => skillOverrideIds.includes(s.id))
                        : botSkills.every((s) => skillDisabledList.includes(s.id)))
                        ? "none" : "all"}
                    </Text>
                  </Pressable>
                </View>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 2 }}>
                  {botSkills.filter((s) => !q || s.id.toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q)).map((skill) => {
                    const checked = skillMode === "override"
                      ? skillOverrideIds.includes(skill.id)
                      : skillDisabledList.includes(skill.id);
                    return (
                      <Pressable
                        key={skill.id}
                        onPress={() => toggleSkill(skill.id)}
                        style={{
                          flexDirection: "row", alignItems: "center", gap: 6,
                          padding: 4, paddingHorizontal: 8, borderRadius: 4, width: "49%",
                          backgroundColor: checked ? "rgba(59,130,246,0.08)" : "transparent",
                          borderWidth: 1, borderColor: checked ? "#3b82f622" : "transparent",
                        }}
                      >
                        <input
                          type="checkbox" checked={checked} readOnly
                          style={{ accentColor: skillMode === "disabled" ? "#ef4444" : t.accent }}
                        />
                        <Text style={{
                          fontSize: 11,
                          color: checked ? (skillMode === "disabled" ? "#dc2626" : "#2563eb") : t.textDim,
                        }} numberOfLines={1}>{skill.name || skill.id}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </>
            )}
          </Section>
        );
      })()}

      {/* Effective tools summary */}
      {effective && (
        <Section title="Effective Configuration">
          <Text style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>
            After applying overrides, this channel has:
          </Text>
          <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {effective.local_tools.length} local tools, {effective.mcp_servers.length} MCP servers, {effective.client_tools.length} client tools, {effective.pinned_tools.length} pinned tools, {effective.skills.length} skills
          </Text>
        </Section>
      )}
    </>
  );
}
