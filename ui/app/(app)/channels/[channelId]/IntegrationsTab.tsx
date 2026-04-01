import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Plus, X, Pencil, Check, AlertTriangle, Zap, Power } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  useAvailableIntegrations,
  useActivatableIntegrations,
  useActivateIntegration,
  useDeactivateIntegration,
  type AvailableIntegration,
} from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, EmptyState,
} from "@/src/components/shared/FormControls";
import { ActionButton, StatusBadge, InfoBanner } from "@/src/components/shared/SettingsControls";
import type { ActivationResult } from "@/src/types/api";

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
// Activation section
// ---------------------------------------------------------------------------

function ActivationsSection({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  const t = useThemeTokens();
  const { data: integrations, isLoading } = useActivatableIntegrations(channelId);
  const activateMut = useActivateIntegration(channelId);
  const deactivateMut = useDeactivateIntegration(channelId);
  const [warnings, setWarnings] = useState<ActivationResult["warnings"]>([]);
  const [togglingType, setTogglingType] = useState<string | null>(null);

  if (isLoading || !integrations || integrations.length === 0) return null;

  const handleToggle = async (integrationType: string, currentlyActive: boolean) => {
    setTogglingType(integrationType);
    setWarnings([]);
    try {
      if (currentlyActive) {
        await deactivateMut.mutateAsync(integrationType);
      } else {
        const result = await activateMut.mutateAsync(integrationType);
        if (result.warnings?.length) {
          setWarnings(result.warnings);
        }
      }
    } finally {
      setTogglingType(null);
    }
  };

  return (
    <Section
      title="Integration Features"
      description="Enable integration features on this channel."
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {integrations.map((ig) => {
          const disabled = ig.requires_workspace && !workspaceEnabled && !ig.activated;
          const toggling = togglingType === ig.integration_type;

          return (
            <div
              key={ig.integration_type}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 14px",
                borderRadius: 10,
                border: `1px solid ${ig.activated ? t.accentBorder : t.surfaceBorder}`,
                background: ig.activated ? t.accentSubtle : t.surfaceRaised,
                transition: "all 0.15s ease",
              }}
            >
              {/* Icon */}
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 8,
                  background: ig.activated ? t.accent : t.surfaceOverlay,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  transition: "background 0.15s",
                }}
              >
                <Zap
                  size={16}
                  color={ig.activated ? "#fff" : t.textDim}
                  fill={ig.activated ? "#fff" : "none"}
                />
              </div>

              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                    {ig.integration_type}
                  </span>
                  {ig.activated && (
                    <StatusBadge label="Active" variant="success" />
                  )}
                  {ig.requires_workspace && !workspaceEnabled && (
                    <StatusBadge label="Requires workspace" variant="warning" />
                  )}
                </div>
                {ig.description && (
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 3, lineHeight: "1.4" }}>
                    {ig.description}
                  </div>
                )}
              </div>

              {/* Toggle button */}
              <button
                onClick={() => !disabled && !toggling && handleToggle(ig.integration_type, ig.activated)}
                disabled={disabled || toggling}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: ig.activated
                    ? `1px solid ${t.dangerBorder}`
                    : `1px solid ${t.accentBorder}`,
                  background: ig.activated ? "transparent" : t.accent,
                  color: ig.activated ? t.danger : "#fff",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: disabled || toggling ? "not-allowed" : "pointer",
                  opacity: disabled ? 0.4 : 1,
                  flexShrink: 0,
                  transition: "all 0.12s",
                }}
              >
                {toggling ? (
                  <ActivityIndicator size={12} color={ig.activated ? t.danger : "#fff"} />
                ) : (
                  <Power size={12} />
                )}
                {ig.activated ? "Deactivate" : "Activate"}
              </button>
            </div>
          );
        })}
      </div>

      {/* Warnings from activation */}
      {warnings.length > 0 && (
        <InfoBanner
          variant="warning"
          icon={<AlertTriangle size={14} />}
        >
          <div>
            {warnings.map((w, i) => (
              <div key={i}>{w.message}</div>
            ))}
          </div>
        </InfoBanner>
      )}
    </Section>
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
export function IntegrationsTab({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
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
      {/* Activation section — above dispatcher bindings */}
      <ActivationsSection
        channelId={channelId}
        workspaceEnabled={workspaceEnabled}
      />

      <Section title="Dispatcher Bindings" description="Route bot responses to external services.">
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
                <div
                  key={b.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 14px",
                    borderRadius: 10,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: t.surfaceRaised,
                  }}
                >
                  <StatusBadge label={b.integration_type} variant="info" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {b.client_id}
                    </div>
                    {b.display_name && (
                      <div style={{ fontSize: 11, color: t.textDim, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {b.display_name}
                      </div>
                    )}
                    {eventFilter.length > 0 && (
                      <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                        Events: {eventFilter.join(", ")}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => setEditingId(b.id)}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    <Pencil size={13} color={t.textDim} />
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Unbind "${b.integration_type}" integration (${b.client_id})?`)) {
                        unbindMutation.mutate(b.id);
                      }
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    <X size={14} color={t.danger} />
                  </button>
                </div>
              );
            })}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <ActionButton
          label="Add Binding"
          onPress={() => setShowAdd(true)}
          variant="secondary"
          size="small"
          icon={<Plus size={12} />}
        />
      ) : (
        <Section title="Add Binding">
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
