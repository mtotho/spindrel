import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Plus, X, Pencil, Check } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  useAvailableIntegrations,
  type AvailableIntegration,
} from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, EmptyState,
} from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// Binding form (shared between Add and Edit)
// ---------------------------------------------------------------------------

function BindingForm({
  availableIntegrations,
  initialType,
  initialClientId,
  initialDisplayName,
  onSubmit,
  onCancel,
  isPending,
  isError,
  errorMessage,
  submitLabel,
  lockType,
}: {
  availableIntegrations: AvailableIntegration[];
  initialType: string;
  initialClientId: string;
  initialDisplayName: string;
  onSubmit: (type: string, clientId: string, displayName: string) => void;
  onCancel: () => void;
  isPending: boolean;
  isError: boolean;
  errorMessage?: string;
  submitLabel: string;
  lockType?: boolean;
}) {
  const t = useThemeTokens();
  const [type, setType] = useState(initialType);
  const [clientId, setClientId] = useState(initialClientId);
  const [displayName, setDisplayName] = useState(initialDisplayName);

  const selected = availableIntegrations.find((i) => i.type === type);
  const binding = selected?.binding;

  const handleTypeChange = (newType: string) => {
    setType(newType);
    // Auto-set prefix when switching types
    const newBinding = availableIntegrations.find((i) => i.type === newType)?.binding;
    if (newBinding?.client_id_prefix && !clientId) {
      setClientId(newBinding.client_id_prefix);
    }
  };

  return (
    <View className="gap-3">
      <FormRow label="Type">
        {lockType ? (
          <Text className="text-accent text-sm font-semibold">{type}</Text>
        ) : (
          <SelectInput
            value={type}
            onChange={handleTypeChange}
            options={availableIntegrations.map((i) => ({ label: i.type, value: i.type }))}
          />
        )}
      </FormRow>
      <FormRow
        label="Client ID"
        description={binding?.client_id_description}
      >
        <TextInput
          value={clientId}
          onChangeText={setClientId}
          placeholder={binding?.client_id_placeholder ?? `${type}:...`}
        />
      </FormRow>
      <FormRow label="Display Name (optional)">
        <TextInput
          value={displayName}
          onChangeText={setDisplayName}
          placeholder={binding?.display_name_placeholder ?? ""}
        />
      </FormRow>
      <View className="flex-row gap-2">
        <Pressable
          onPress={() => onSubmit(type, clientId.trim(), displayName.trim())}
          disabled={!type || !clientId.trim() || isPending}
          style={{
            backgroundColor: type && clientId.trim() ? t.accent : t.surfaceBorder,
            paddingHorizontal: 14,
            paddingVertical: 7,
            borderRadius: 8,
          }}
        >
          <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
            {isPending ? "Saving..." : submitLabel}
          </Text>
        </Pressable>
        <Pressable
          onPress={onCancel}
          className="px-3 py-1.5 rounded-lg hover:bg-surface-overlay"
        >
          <Text className="text-text-muted text-sm">Cancel</Text>
        </Pressable>
      </View>
      {isError && (
        <Text className="text-red-400 text-xs">
          {errorMessage ?? "Failed"}
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Integrations Tab
// ---------------------------------------------------------------------------
export function IntegrationsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const { data: bindings, isLoading } = useChannelIntegrations(channelId);
  const { data: availableIntegrations } = useAvailableIntegrations();
  const bindMutation = useBindIntegration(channelId);
  const unbindMutation = useUnbindIntegration(channelId);

  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const available = availableIntegrations ?? [];

  const handleAdd = async (type: string, clientId: string, displayName: string) => {
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
    });
    setShowAdd(false);
  };

  const handleEdit = async (bindingId: string, type: string, clientId: string, displayName: string) => {
    // Unbind old, bind new
    await unbindMutation.mutateAsync(bindingId);
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
    });
    setEditingId(null);
  };

  if (isLoading) return <ActivityIndicator color={t.accent} />;

  return (
    <>
      <Section title="Integration Bindings">
        {(!bindings || bindings.length === 0) ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <View className="gap-2">
            {bindings.map((b) =>
              editingId === b.id ? (
                <View
                  key={b.id}
                  className="bg-surface-raised border border-surface-border rounded-lg p-3"
                >
                  <BindingForm
                    availableIntegrations={available}
                    initialType={b.integration_type}
                    initialClientId={b.client_id}
                    initialDisplayName={b.display_name ?? ""}
                    onSubmit={(type, clientId, displayName) =>
                      handleEdit(b.id, type, clientId, displayName)
                    }
                    onCancel={() => setEditingId(null)}
                    isPending={bindMutation.isPending || unbindMutation.isPending}
                    isError={bindMutation.isError}
                    errorMessage={bindMutation.error instanceof Error ? bindMutation.error.message : undefined}
                    submitLabel="Save"
                    lockType
                  />
                </View>
              ) : (
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
                    onPress={() => setEditingId(b.id)}
                    className="p-1 rounded hover:bg-surface-overlay"
                  >
                    <Pencil size={13} color={t.textDim} />
                  </Pressable>
                  <Pressable
                    onPress={() => unbindMutation.mutate(b.id)}
                    className="p-1 rounded hover:bg-surface-overlay"
                  >
                    <X size={14} color={t.danger} />
                  </Pressable>
                </View>
              )
            )}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <Pressable
          onPress={() => setShowAdd(true)}
          className="flex-row items-center gap-2 px-3 py-2"
        >
          <Plus size={14} color={t.accent} />
          <Text className="text-accent text-sm font-medium">Add Integration</Text>
        </Pressable>
      ) : (
        <Section title="Add Integration">
          <BindingForm
            availableIntegrations={available}
            initialType={available[0]?.type ?? ""}
            initialClientId=""
            initialDisplayName=""
            onSubmit={handleAdd}
            onCancel={() => setShowAdd(false)}
            isPending={bindMutation.isPending}
            isError={bindMutation.isError}
            errorMessage={bindMutation.error instanceof Error ? bindMutation.error.message : undefined}
            submitLabel="Bind"
          />
        </Section>
      )}
    </>
  );
}
