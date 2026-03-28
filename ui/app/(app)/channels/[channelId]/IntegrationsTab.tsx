import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Plus, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  useAvailableIntegrations,
} from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, EmptyState,
} from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// Integrations Tab
// ---------------------------------------------------------------------------
export function IntegrationsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const { data: bindings, isLoading } = useChannelIntegrations(channelId);
  const { data: availableTypes } = useAvailableIntegrations();
  const bindMutation = useBindIntegration(channelId);
  const unbindMutation = useUnbindIntegration(channelId);

  const [showAdd, setShowAdd] = useState(false);
  const [newType, setNewType] = useState("");
  const [newClientId, setNewClientId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");

  const handleBind = async () => {
    if (!newType || !newClientId.trim()) return;
    await bindMutation.mutateAsync({
      integration_type: newType,
      client_id: newClientId.trim(),
      display_name: newDisplayName.trim() || undefined,
    });
    setShowAdd(false);
    setNewType("");
    setNewClientId("");
    setNewDisplayName("");
  };

  if (isLoading) return <ActivityIndicator color={t.accent} />;

  return (
    <>
      <Section title="Integration Bindings">
        {(!bindings || bindings.length === 0) ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <View className="gap-2">
            {bindings.map((b) => (
              <View key={b.id} className="flex-row items-center gap-3 bg-surface-raised border border-surface-border rounded-lg px-3 py-2">
                <Text className="text-accent text-xs font-semibold bg-accent/15 px-2 py-0.5 rounded">
                  {b.integration_type}
                </Text>
                <View className="flex-1 min-w-0">
                  <Text className="text-text text-sm" numberOfLines={1}>{b.client_id}</Text>
                  {b.display_name && (
                    <Text className="text-text-muted text-xs" numberOfLines={1}>{b.display_name}</Text>
                  )}
                </View>
                <Pressable
                  onPress={() => unbindMutation.mutate(b.id)}
                  className="p-1 rounded hover:bg-surface-overlay"
                >
                  <X size={14} color="#ef4444" />
                </Pressable>
              </View>
            ))}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <Pressable
          onPress={() => {
            setShowAdd(true);
            if (availableTypes?.length && !newType) setNewType(availableTypes[0]);
          }}
          className="flex-row items-center gap-2 px-3 py-2"
        >
          <Plus size={14} color={t.accent} />
          <Text className="text-accent text-sm font-medium">Add Integration</Text>
        </Pressable>
      ) : (
        <Section title="Add Integration">
          <View className="gap-3">
            <FormRow label="Type">
              <SelectInput
                value={newType}
                onChange={setNewType}
                options={(availableTypes ?? []).map((t) => ({ label: t, value: t }))}
              />
            </FormRow>
            <FormRow label="Client ID">
              <TextInput
                value={newClientId}
                onChangeText={setNewClientId}
                placeholder="slack:C01ABC123"
              />
            </FormRow>
            <FormRow label="Display Name (optional)">
              <TextInput
                value={newDisplayName}
                onChangeText={setNewDisplayName}
                placeholder="#general"
              />
            </FormRow>
            <View className="flex-row gap-2">
              <Pressable
                onPress={handleBind}
                disabled={!newType || !newClientId.trim() || bindMutation.isPending}
                style={{
                  backgroundColor: newType && newClientId.trim() ? t.accent : t.surfaceBorder,
                  paddingHorizontal: 14,
                  paddingVertical: 7,
                  borderRadius: 8,
                }}
              >
                <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
                  {bindMutation.isPending ? "Binding..." : "Bind"}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => setShowAdd(false)}
                className="px-3 py-1.5 rounded-lg hover:bg-surface-overlay"
              >
                <Text className="text-text-muted text-sm">Cancel</Text>
              </Pressable>
            </View>
            {bindMutation.isError && (
              <Text className="text-red-400 text-xs">
                {bindMutation.error instanceof Error ? bindMutation.error.message : "Failed to bind"}
              </Text>
            )}
          </View>
        </Section>
      )}
    </>
  );
}
