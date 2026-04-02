import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { FileText, Zap, Wrench, BookOpen } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useActivatableIntegrations, useChannelSettings } from "@/src/api/hooks/useChannels";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";

/**
 * Compact horizontal strip showing what's active on this channel:
 * template badge, active integration badges, tool/skill count.
 * Clicking a badge navigates to the relevant settings tab.
 */
export function ActiveBadgeBar({ channelId }: { channelId: string }) {
  const theme = useThemeTokens();
  const router = useRouter();
  const { data: settings } = useChannelSettings(channelId);
  const workspaceEnabled = settings?.channel_workspace_enabled;
  // Only fetch activatable/templates if channel has workspace or integrations to show
  const { data: activatable } = useActivatableIntegrations(channelId);
  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");

  const activeIntegrations = activatable?.filter((ig) => ig.activated) ?? [];
  const templateId = settings?.workspace_schema_template_id;
  const template = templateId ? templates?.find((tpl) => tpl.id === templateId) : null;

  // Compute total tools/skills from active integrations
  const totalTools = activeIntegrations.reduce((sum, ig) => sum + (ig.tools?.length ?? 0), 0);
  const totalSkills = activeIntegrations.reduce((sum, ig) => sum + (ig.skill_count ?? 0), 0);

  // Nothing active? Don't render
  if (!workspaceEnabled && activeIntegrations.length === 0) return null;

  const nav = (hash: string) => router.push(`/channels/${channelId}/settings#${hash}` as any);

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
      {/* Template badge */}
      {template && (
        <Pressable onPress={() => nav("workspace")} style={badgeStyle(theme.accent + "15", theme.accent + "40")}>
          <FileText size={11} color={theme.accent} />
          <Text numberOfLines={1} style={{ fontSize: 11, color: theme.accent, fontWeight: "500", maxWidth: 160 }}>
            {template.name}
          </Text>
        </Pressable>
      )}

      {/* Active integrations */}
      {activeIntegrations.map((ig) => (
        <Pressable
          key={ig.integration_type}
          onPress={() => nav("integrations")}
          style={badgeStyle(theme.success + "15", theme.success + "40")}
        >
          <Zap size={11} color={theme.success} />
          <Text numberOfLines={1} style={{ fontSize: 11, color: theme.success, fontWeight: "500", maxWidth: 140 }}>
            {ig.integration_type.replace(/_/g, " ")}
          </Text>
        </Pressable>
      ))}

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
