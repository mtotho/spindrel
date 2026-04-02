import { View, Text, Switch } from "react-native";
import { Plug, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import type { ActivatableIntegration } from "../../types/api";

interface IntegrationActivationListProps {
  integrations: ActivatableIntegration[];
  enabled: string[];
  onToggle: (integrationType: string) => void;
  workspaceEnabled: boolean;
}

export function IntegrationActivationList({
  integrations,
  enabled,
  onToggle,
  workspaceEnabled,
}: IntegrationActivationListProps) {
  const t = useThemeTokens();

  if (integrations.length === 0) return null;

  return (
    <View style={{ gap: 10 }}>
      {integrations.map((integration) => {
        const isEnabled = enabled.includes(integration.integration_type);
        const needsWorkspace = integration.requires_workspace && !workspaceEnabled;

        return (
          <View
            key={integration.integration_type}
            style={{
              borderWidth: 1,
              borderColor: isEnabled ? t.accent + "40" : t.surfaceBorder,
              backgroundColor: isEnabled ? t.accent + "08" : "transparent",
              borderRadius: 10,
              padding: 14,
              gap: 6,
              opacity: needsWorkspace ? 0.5 : 1,
            }}
          >
            <View className="flex-row items-center gap-3">
              <Plug size={16} color={isEnabled ? t.accent : t.textDim} />
              <View style={{ flex: 1 }}>
                <Text className={`text-sm font-medium ${isEnabled ? "text-accent" : "text-text"}`}>
                  {integration.integration_type.replace(/_/g, " ")}
                </Text>
                {integration.description && (
                  <Text className="text-text-muted text-xs" numberOfLines={1}>
                    {integration.description}
                  </Text>
                )}
              </View>
              <Switch
                value={isEnabled}
                onValueChange={() => {
                  if (!needsWorkspace) onToggle(integration.integration_type);
                }}
                disabled={needsWorkspace}
                trackColor={{ false: t.surfaceBorder, true: t.accent }}
              />
            </View>

            {/* What it provides */}
            <View className="flex-row flex-wrap gap-1.5" style={{ marginLeft: 28 }}>
              {integration.tools.length > 0 && (
                <View style={{ backgroundColor: t.surfaceBorder, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 }}>
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    {integration.tools.length} tool{integration.tools.length !== 1 ? "s" : ""}
                  </Text>
                </View>
              )}
              {integration.skill_count > 0 && (
                <View style={{ backgroundColor: t.surfaceBorder, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 }}>
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    {integration.skill_count} skill{integration.skill_count !== 1 ? "s" : ""}
                  </Text>
                </View>
              )}
              {integration.carapaces.length > 0 && (
                <View style={{ backgroundColor: t.surfaceBorder, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 }}>
                  <Text style={{ fontSize: 10, color: t.textDim }}>
                    via {integration.carapaces.join(", ")}
                  </Text>
                </View>
              )}
            </View>

            {needsWorkspace && (
              <View className="flex-row items-center gap-1.5" style={{ marginLeft: 28 }}>
                <AlertTriangle size={12} color={t.warning} />
                <Text style={{ fontSize: 11, color: t.warning }}>
                  Requires workspace — select a template first
                </Text>
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}
