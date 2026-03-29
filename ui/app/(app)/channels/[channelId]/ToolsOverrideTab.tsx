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
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";
import { EffectiveToolsList } from "./EffectiveToolsList";
import { EffectiveSkillsList } from "./EffectiveSkillsList";

export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
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
    } as any);
  }, [save]);

  if (editorLoading) {
    return <ActivityIndicator size="small" color={t.textDim} />;
  }

  if (!editorData || !settings || !effective) {
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
    settings.skills_extra != null;

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

      {/* Search */}
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
          placeholder="Search tools & skills..."
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

      {/* Legend */}
      <View style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 10, color: t.textDim }}>
          All tools are active by default. Uncheck to disable at the channel level. Changes save immediately.
        </Text>
      </View>

      {/* Tools */}
      <Section title="Tools">
        <EffectiveToolsList
          editorData={editorData}
          settings={settings}
          effective={effective}
          filter={filter}
          onSave={save}
        />
      </Section>

      {/* Skills */}
      <Section title="Skills">
        <EffectiveSkillsList
          editorData={editorData}
          settings={settings}
          effective={effective}
          filter={filter}
          onSave={save}
        />
      </Section>

      {/* Summary */}
      <Section title="Summary">
        <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
          {effective.local_tools.length} local tools, {effective.mcp_servers.length} MCP servers,{" "}
          {effective.client_tools.length} client tools, {effective.pinned_tools.length} pinned,{" "}
          {effective.skills.length} skills
        </Text>
      </Section>
    </>
  );
}
