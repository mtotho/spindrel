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
  const theme = useThemeTokens();
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
        <Pressable onPress={() => nav("workspace")} style={badgeStyle(theme.accent + "15", theme.accent + "40")}>
          <FileText size={11} color={theme.accent} />
          <Text numberOfLines={1} style={{ fontSize: 11, color: theme.accent, fontWeight: "500", maxWidth: 160 }}>
            {template.name}
          </Text>
        </Pressable>
      )}

      {/* Activated integrations — green, with proper icons */}
      {activeIntegrations.map((ig) => {
        const Icon = resolveIcon(icons[ig.integration_type]);
        return (
          <Pressable
            key={ig.integration_type}
            onPress={() => nav("integrations")}
            style={badgeStyle(theme.success + "15", theme.success + "40")}
          >
            <Icon size={11} color={theme.success} />
            <Text numberOfLines={1} style={{ fontSize: 11, color: theme.success, fontWeight: "500", maxWidth: 140 }}>
              {prettyIntegrationName(ig.integration_type)}
            </Text>
          </Pressable>
        );
      })}

      {/* Bound-only integrations — subtle, just shows connection */}
      {boundOnly.map((b) => {
        const Icon = resolveIcon(icons[b.integration_type]);
        return (
          <Pressable
            key={b.id}
            onPress={() => nav("integrations")}
            style={badgeStyle(theme.surfaceOverlay, theme.surfaceBorder)}
          >
            <Icon size={11} color={theme.textDim} />
            <Text numberOfLines={1} style={{ fontSize: 11, color: theme.textDim, fontWeight: "500", maxWidth: 140 }}>
              {prettyIntegrationName(b.integration_type)}
            </Text>
          </Pressable>
        );
      })}

      {/* Separator dot before counts */}
      {(totalTools > 0 || totalSkills > 0) && (template || activeIntegrations.length > 0 || boundOnly.length > 0) && (
        <Text style={{ fontSize: 10, color: theme.textDim, opacity: 0.4 }}>{"\u00b7"}</Text>
      )}

      {/* Tool/skill count summary */}
      {totalTools > 0 && (
        <Pressable onPress={() => nav("tools")} style={badgeStyle(theme.surfaceOverlay, theme.surfaceBorder)}>
          <Wrench size={10} color={theme.textDim} />
          <Text style={{ fontSize: 10, color: theme.textDim }}>
            {totalTools} tool{totalTools !== 1 ? "s" : ""}
          </Text>
        </Pressable>
      )}
      {totalSkills > 0 && (
        <Pressable onPress={() => nav("integrations")} style={badgeStyle(theme.surfaceOverlay, theme.surfaceBorder)}>
          <BookOpen size={10} color={theme.textDim} />
          <Text style={{ fontSize: 10, color: theme.textDim }}>
            {totalSkills} skill{totalSkills !== 1 ? "s" : ""}
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
        className="border-b border-surface-border"
        style={{ flexShrink: 0, backgroundColor: theme.surface }}
        contentContainerStyle={{
          paddingHorizontal: 12,
          paddingVertical: 4,
          gap: 6,
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
        paddingVertical: 5,
        gap: 6,
        flexWrap: "wrap",
        backgroundColor: theme.surface,
      }}
    >
      {badges}
    </View>
  );
}

function badgeStyle(bg: string, border: string) {
  return {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 5,
    backgroundColor: bg,
    borderWidth: 1,
    borderColor: border,
  };
}
