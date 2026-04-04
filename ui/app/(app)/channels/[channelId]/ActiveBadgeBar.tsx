import { View, Text, Pressable, ScrollView } from "react-native";
import { useRouter } from "expo-router";
import {
  FileText, Wrench, BookOpen, Plug,
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useActivatableIntegrations, useChannelSettings, useChannel } from "@/src/api/hooks/useChannels";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { useIntegrationIcons } from "@/src/api/hooks/useIntegrations";
import { prettyIntegrationName } from "@/src/utils/format";

/** Map lucide icon name strings to components. */
const ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  MessageSquare, Code2, Mail, Camera, LayoutDashboard, Tv, Terminal, MessageCircle, Plug,
};
function resolveIcon(name: string | undefined): React.ComponentType<{ size: number; color: string }> {
  return (name && ICON_MAP[name]) || Plug;
}

/**
 * Compact horizontal strip showing what's active on this channel:
 * template badge, active/bound integration badges, tool/skill counts.
 * Clicking a badge navigates to the relevant settings tab.
 */
export function ActiveBadgeBar({ channelId, compact }: { channelId: string; compact?: boolean }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: settings } = useChannelSettings(channelId);
  const { data: channel } = useChannel(channelId);
  const { data: activatable } = useActivatableIntegrations(channelId);
  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");
  const { data: iconsData } = useIntegrationIcons();
  const icons = iconsData?.icons ?? {};

  const activeIntegrations = activatable?.filter((ig) => ig.activated) ?? [];
  const activeTypes = new Set(activeIntegrations.map((ig) => ig.integration_type));

  // Bound integrations that are NOT activated (just connected — e.g., Slack dispatch)
  const boundOnly = (channel?.integrations ?? []).filter(
    (b) => !activeTypes.has(b.integration_type)
  );

  const templateId = settings?.workspace_schema_template_id;
  const template = templateId ? templates?.find((tpl) => tpl.id === templateId) : null;

  // Tool/skill counts from activated integrations
  const totalTools = activeIntegrations.reduce((sum, ig) => sum + (ig.tools?.length ?? 0), 0);
  const totalSkills = activeIntegrations.reduce((sum, ig) => sum + (ig.skill_count ?? 0), 0);

  // Nothing to show? Don't render the bar
  const hasAnything = template || activeIntegrations.length > 0 || boundOnly.length > 0;
  if (!hasAnything) return null;

  const nav = (hash: string) => router.push(`/channels/${channelId}/settings#${hash}` as any);

  const badges = (
    <>
      {/* Template badge */}
      {template && (
        <Pressable onPress={() => nav("workspace")} style={pillStyle}>
          <FileText size={11} color={t.accent} />
          <Text numberOfLines={1} style={{ fontSize: 11, color: t.accent, fontWeight: "500", maxWidth: 160 }}>
            {template.name}
          </Text>
        </Pressable>
      )}

      {/* Activated integrations — green dot + name */}
      {activeIntegrations.map((ig) => {
        const Icon = resolveIcon(icons[ig.integration_type]);
        return (
          <Pressable key={ig.integration_type} onPress={() => nav("integrations")} style={pillStyle}>
            <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.success }} />
            <Text numberOfLines={1} style={{ fontSize: 11, color: t.textMuted, fontWeight: "500", maxWidth: 140 }}>
              {prettyIntegrationName(ig.integration_type)}
            </Text>
          </Pressable>
        );
      })}

      {/* Bound-only integrations — dim dot + name */}
      {boundOnly.map((b) => (
        <Pressable key={b.id} onPress={() => nav("integrations")} style={pillStyle}>
          <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.textDim, opacity: 0.5 }} />
          <Text numberOfLines={1} style={{ fontSize: 11, color: t.textDim, fontWeight: "500", maxWidth: 140 }}>
            {prettyIntegrationName(b.integration_type)}
          </Text>
        </Pressable>
      ))}

      {/* Tool/skill counts — inline text, no pill */}
      {totalTools > 0 && (
        <Pressable onPress={() => nav("tools")} style={pillStyle}>
          <Wrench size={10} color={t.textDim} />
          <Text style={{ fontSize: 10, color: t.textDim }}>
            {totalTools}
          </Text>
        </Pressable>
      )}
      {totalSkills > 0 && (
        <Pressable onPress={() => nav("integrations")} style={pillStyle}>
          <BookOpen size={10} color={t.textDim} />
          <Text style={{ fontSize: 10, color: t.textDim }}>
            {totalSkills}
          </Text>
        </Pressable>
      )}
    </>
  );

  // Compact mode: horizontal scroll, single row, no wrap (mobile)
  if (compact) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={{ flexShrink: 0, maxHeight: 26, borderBottomWidth: 1, borderBottomColor: t.surfaceBorder }}
        contentContainerStyle={{
          paddingHorizontal: 12,
          paddingVertical: 4,
          gap: 12,
          alignItems: "center",
          flexDirection: "row",
        }}
      >
        {badges}
      </ScrollView>
    );
  }

  // Default: wrapping row (desktop)
  return (
    <View
      className="flex-row items-center border-b border-surface-border"
      style={{
        paddingHorizontal: 16,
        paddingVertical: 4,
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      {badges}
    </View>
  );
}

const pillStyle = {
  flexDirection: "row" as const,
  alignItems: "center" as const,
  gap: 4,
};
