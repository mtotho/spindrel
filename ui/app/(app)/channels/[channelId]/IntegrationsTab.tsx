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
import { ActionButton } from "@/src/components/shared/SettingsControls";

// ---------------------------------------------------------------------------
// Event filter multi-select
// ---------------------------------------------------------------------------

function EventFilterPicker({
  eventTypes,
  selected,
  onChange,
}: {
  eventTypes: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const t = useThemeTokens();

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <View className="gap-1.5">
      {eventTypes.map((et) => {
        const isChecked = selected.includes(et.value);
        return (
          <Pressable
            key={et.value}
            onPress={() => toggle(et.value)}
            className="flex-row items-center gap-2"
          >
            <View
              style={{
                width: 16,
                height: 16,
                borderRadius: 3,
                borderWidth: 1.5,
                borderColor: isChecked ? t.accent : t.surfaceBorder,
                backgroundColor: isChecked ? t.accent : "transparent",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isChecked && <Check size={11} color="#fff" strokeWidth={3} />}
            </View>
            <Text className="text-text text-sm">{et.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Binding form (shared between Add and Edit)
// ---------------------------------------------------------------------------

function BindingForm({
  availableIntegrations,
  initialType,
  initialClientId,
  initialDisplayName,
  initialEventFilter,
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
  initialEventFilter?: string[];
  onSubmit: (type: string, clientId: string, displayName: string, eventFilter: string[]) => void;
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
  const [eventFilter, setEventFilter] = useState<string[]>(initialEventFilter ?? []);

  const selected = availableIntegrations.find((i) => i.type === type);
  const binding = selected?.binding;
  const eventTypes = binding?.event_types;

  const handleTypeChange = (newType: string) => {
    setType(newType);
    setEventFilter([]);
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
      {eventTypes && eventTypes.length > 0 && (
        <FormRow
          label="Event Filter"
          description="Select which events this binding receives. Empty = all events."
        >
          <EventFilterPicker
            eventTypes={eventTypes}
            selected={eventFilter}
            onChange={setEventFilter}
          />
        </FormRow>
      )}
      <View className="flex-row gap-2">
        <ActionButton
          label={isPending ? "Saving..." : submitLabel}
          onPress={() => onSubmit(type, clientId.trim(), displayName.trim(), eventFilter)}
          disabled={!type || !clientId.trim() || isPending}
          size="small"
        />
        <ActionButton
          label="Cancel"
          onPress={onCancel}
          variant="ghost"
          size="small"
        />
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

  const handleAdd = async (type: string, clientId: string, displayName: string, eventFilter: string[]) => {
    const dispatchConfig: Record<string, any> = {};
    if (eventFilter.length > 0) {
      dispatchConfig.event_filter = eventFilter;
    }
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
    });
    setShowAdd(false);
  };

  const handleEdit = async (bindingId: string, type: string, clientId: string, displayName: string, eventFilter: string[]) => {
    const dispatchConfig: Record<string, any> = {};
    if (eventFilter.length > 0) {
      dispatchConfig.event_filter = eventFilter;
    }
    // Unbind old, bind new
    await unbindMutation.mutateAsync(bindingId);
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
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
            {bindings.map((b) => {
              const eventFilter: string[] = b.dispatch_config?.event_filter ?? [];
              return editingId === b.id ? (
                <View
                  key={b.id}
                  className="bg-surface-raised border border-surface-border rounded-lg p-3"
                >
                  <BindingForm
                    availableIntegrations={available}
                    initialType={b.integration_type}
                    initialClientId={b.client_id}
                    initialDisplayName={b.display_name ?? ""}
                    initialEventFilter={eventFilter}
                    onSubmit={(type, clientId, displayName, ef) =>
                      handleEdit(b.id, type, clientId, displayName, ef)
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
                    {eventFilter.length > 0 && (
                      <Text className="text-text-dim text-xs" numberOfLines={1}>
                        Events: {eventFilter.join(", ")}
                      </Text>
                    )}
                  </View>
                  <Pressable
                    onPress={() => setEditingId(b.id)}
                    className="p-1 rounded hover:bg-surface-overlay"
                  >
                    <Pencil size={13} color={t.textDim} />
                  </Pressable>
                  <Pressable
                    onPress={() => {
                      if (confirm(`Unbind "${b.integration_type}" integration (${b.client_id})?`)) {
                        unbindMutation.mutate(b.id);
                      }
                    }}
                    className="p-1 rounded hover:bg-surface-overlay"
                  >
                    <X size={14} color={t.danger} />
                  </Pressable>
                </View>
              );
            })}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <ActionButton
          label="Add Integration"
          onPress={() => setShowAdd(true)}
          variant="secondary"
          size="small"
          icon={<Plus size={12} />}
        />
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
