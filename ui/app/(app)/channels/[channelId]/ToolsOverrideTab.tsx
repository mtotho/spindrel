import { useState, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Check, Search, X, RotateCcw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannelEffectiveTools,
} from "@/src/api/hooks/useChannels";
import { useBotEditorData } from "@/src/api/hooks/useBots";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";
import { EffectiveToolsList } from "./EffectiveToolsList";
import { EffectiveSkillsList } from "./EffectiveSkillsList";

export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
  const { data: allCarapaces } = useCarapaces();
  const updateMutation = useUpdateChannelSettings(channelId);
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);

  const save = useCallback(
    async (patch: Partial<ChannelSettings>) => {
      setSaved(false);
      await updateMutation.mutateAsync(patch);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
    [updateMutation],
  );

  const handleResetAll = useCallback(() => {
    save({
      local_tools_override: null,
      local_tools_disabled: null,
      mcp_servers_override: null,
      mcp_servers_disabled: null,
      client_tools_override: null,
      client_tools_disabled: null,
      pinned_tools_override: null,
      skills_override: null,
      skills_disabled: null,
      skills_extra: null,
      carapaces_extra: null,
      carapaces_disabled: null,
    } as any);
  }, [save]);

  const toggleCarapaceExtra = useCallback(
    (carapaceId: string) => {
      const current = settings?.carapaces_extra ?? [];
      const next = current.includes(carapaceId)
        ? current.filter((c) => c !== carapaceId)
        : [...current, carapaceId];
      save({ carapaces_extra: next.length > 0 ? next : null } as any);
    },
    [settings, save],
  );

  const toggleCarapaceDisabled = useCallback(
    (carapaceId: string) => {
      const current = settings?.carapaces_disabled ?? [];
      const next = current.includes(carapaceId)
        ? current.filter((c) => c !== carapaceId)
        : [...current, carapaceId];
      save({ carapaces_disabled: next.length > 0 ? next : null } as any);
    },
    [settings, save],
  );

  if (editorLoading) {
    return <ActivityIndicator size="small" color={t.textDim} />;
  }

  if (!editorData || !settings) {
    return <EmptyState message="Loading..." />;
  }

  const hasOverrides =
    settings.local_tools_override != null ||
    settings.local_tools_disabled != null ||
    settings.mcp_servers_override != null ||
    settings.mcp_servers_disabled != null ||
    settings.client_tools_override != null ||
    settings.client_tools_disabled != null ||
    settings.pinned_tools_override != null ||
    settings.skills_override != null ||
    settings.skills_disabled != null ||
    settings.skills_extra != null ||
    settings.carapaces_extra != null ||
    settings.carapaces_disabled != null;

  const extras = new Set(settings.carapaces_extra ?? []);
  const disabled = new Set(settings.carapaces_disabled ?? []);
  const filteredCarapaces = (allCarapaces ?? []).filter(
    (c) => !filter || c.id.includes(filter.toLowerCase()) || c.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <>
      {/* Status + controls */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12 }}>
        {saved && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Check size={12} color={t.success} />
            <Text style={{ color: t.success, fontSize: 11 }}>Saved</Text>
          </View>
        )}
        <View style={{ flex: 1 }} />
        {hasOverrides && (
          <Pressable
            onPress={handleResetAll}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: 8,
              paddingVertical: 3,
              borderRadius: 4,
              borderWidth: 1,
              borderColor: t.surfaceBorder,
            }}
          >
            <RotateCcw size={10} color={t.textDim} />
            <Text style={{ fontSize: 10, color: t.textDim }}>Reset All</Text>
          </Pressable>
        )}
      </View>

      {/* Search (for tools section) */}
      <View
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          background: t.inputBg,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6,
          padding: "5px 10px",
          marginBottom: 12,
        } as any}
      >
        <Search size={12} color={t.textDim} />
        <input
          type="text"
          value={filter}
          onChange={(e: any) => setFilter(e.target.value)}
          placeholder="Search tools, skills & carapaces..."
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: t.text,
            fontSize: 12,
          }}
        />
        {filter && (
          <Pressable onPress={() => setFilter("")}>
            <X size={10} color={t.textDim} />
          </Pressable>
        )}
      </View>

      {/* Carapaces — channel extras/disabled */}
      {filteredCarapaces.length > 0 && (
        <Section title="Channel Carapaces">
          <Text style={{ fontSize: 11, color: t.textMuted, marginBottom: 8 }}>
            Add or disable carapaces for this channel. Extras layer on top of the bot's carapaces.
          </Text>
          {filteredCarapaces.map((c) => {
            const isExtra = extras.has(c.id);
            const isDisabled = disabled.has(c.id);
            return (
              <View
                key={c.id}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  paddingVertical: 4,
                  borderBottomWidth: 1,
                  borderBottomColor: t.surfaceBorder,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: t.text, fontWeight: "500" }}>{c.name}</Text>
                  <Text style={{ fontSize: 10, color: t.textMuted }}>{c.id}{c.description ? ` — ${c.description}` : ""}</Text>
                </View>
                <Pressable
                  onPress={() => toggleCarapaceExtra(c.id)}
                  style={{
                    paddingHorizontal: 8,
                    paddingVertical: 2,
                    borderRadius: 4,
                    borderWidth: 1,
                    borderColor: isExtra ? t.success : t.surfaceBorder,
                    backgroundColor: isExtra ? `${t.success}18` : "transparent",
                  }}
                >
                  <Text style={{ fontSize: 10, color: isExtra ? t.success : t.textDim }}>
                    {isExtra ? "Added" : "Add"}
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => toggleCarapaceDisabled(c.id)}
                  style={{
                    paddingHorizontal: 8,
                    paddingVertical: 2,
                    borderRadius: 4,
                    borderWidth: 1,
                    borderColor: isDisabled ? t.danger : t.surfaceBorder,
                    backgroundColor: isDisabled ? `${t.danger}18` : "transparent",
                  }}
                >
                  <Text style={{ fontSize: 10, color: isDisabled ? t.danger : t.textDim }}>
                    {isDisabled ? "Disabled" : "Disable"}
                  </Text>
                </Pressable>
              </View>
            );
          })}
        </Section>
      )}

      {/* Skills — channel additions */}
      <Section title="Channel Skills">
        <EffectiveSkillsList
          editorData={editorData}
          settings={settings}
          filter={filter}
          onSave={save}
        />
      </Section>

      {/* Tools — disable from bot defaults */}
      <Section title="Tool Overrides">
        <EffectiveToolsList
          editorData={editorData}
          settings={settings}
          filter={filter}
          onSave={save}
        />
      </Section>

      {/* Summary */}
      {effective && (
        <Section title="Effective Summary">
          <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {effective.local_tools.length} local tools, {effective.mcp_servers.length} MCP servers,{" "}
            {effective.client_tools.length} client tools, {effective.pinned_tools.length} pinned,{" "}
            {effective.skills.length} skills, {effective.carapaces.length} carapaces
          </Text>
        </Section>
      )}
    </>
  );
}
