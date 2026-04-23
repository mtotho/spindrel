import { useState } from "react";
import { Plus, Pencil, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelIntegrations,
  useAvailableIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  type AvailableIntegration,
} from "@/src/api/hooks/useChannels";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton, StatusBadge } from "@/src/components/shared/SettingsControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { configSummaryText } from "./helpers";
import { BindingForm } from "./BindingForm";

export function BindingsSection({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const { data: bindings, isLoading } = useChannelIntegrations(channelId);
  const { data: availableIntegrations } = useAvailableIntegrations();
  const bindMutation = useBindIntegration(channelId);
  const unbindMutation = useUnbindIntegration(channelId);

  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [unbindTarget, setUnbindTarget] = useState<{ id: string; type: string; clientId: string } | null>(null);

  const available = availableIntegrations ?? [];

  const handleAdd = async (type: string, clientId: string, displayName: string, dispatchConfig: Record<string, any>) => {
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
    });
    setShowAdd(false);
  };

  const handleEdit = async (bindingId: string, type: string, clientId: string, displayName: string, dispatchConfig: Record<string, any>) => {
    await unbindMutation.mutateAsync(bindingId);
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
    });
    setEditingId(null);
  };

  if (isLoading) {
    return (
      <Section title="Dispatcher Bindings" description="Connect this channel to external messaging services. When the bot responds, its messages are forwarded to the bound service (e.g. a Slack channel or iMessage chat).">
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: 12 }}>
          <span
            style={{
              width: 14,
              height: 14,
              border: `2px solid ${t.accent}`,
              borderTopColor: "transparent",
              borderRadius: "50%",
              display: "inline-block",
              animation: "spin 0.6s linear infinite",
            }}
          />
        </div>
      </Section>
    );
  }

  return (
    <>
      <Section
        title="Dispatcher Bindings"
        description="Connect this channel to external messaging services. When the bot responds, its messages are forwarded to the bound service."
        action={!showAdd ? (
          <ActionButton
            label="Add Binding"
            onPress={() => setShowAdd(true)}
            variant="secondary"
            size="small"
            icon={<Plus size={12} />}
          />
        ) : undefined}
      >
        {(!bindings || bindings.filter((b) => !b.client_id.startsWith("mc-activated:")).length === 0) ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {bindings.filter((b) => !b.client_id.startsWith("mc-activated:")).map((b) => {
              const dc = b.dispatch_config ?? {};
              const summary = configSummaryText(dc, available.find((a) => a.type === b.integration_type)?.binding?.config_fields);
              return editingId === b.id ? (
                <div
                  key={b.id}
                  style={{
                    background: t.surfaceRaised,
                    border: `1px solid ${t.surfaceBorder}`,
                    borderRadius: 7,
                    padding: 12,
                  }}
                >
                  <BindingForm
                    availableIntegrations={available}
                    initialType={b.integration_type}
                    initialClientId={b.client_id}
                    initialDisplayName={b.display_name ?? ""}
                    initialDispatchConfig={dc}
                    onSubmit={(type, clientId, displayName, dispatchConfig) =>
                      handleEdit(b.id, type, clientId, displayName, dispatchConfig)
                    }
                    onCancel={() => setEditingId(null)}
                    isPending={bindMutation.isPending || unbindMutation.isPending}
                    isError={bindMutation.isError}
                    errorMessage={bindMutation.error instanceof Error ? bindMutation.error.message : undefined}
                    submitLabel="Save"
                    lockType
                  />
                </div>
              ) : (
                <div
                  key={b.id}
                  style={{
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 14px",
                    borderRadius: 7,
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
                    {summary && (
                      <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                        {summary}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => setEditingId(b.id)}
                    style={{
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <Pencil size={13} color={t.textDim} />
                  </button>
                  <button
                    onClick={() => setUnbindTarget({ id: b.id, type: b.integration_type, clientId: b.client_id })}
                    style={{
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <X size={14} color={t.danger} />
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {showAdd && (
          <div
            style={{
              marginTop: 4,
              padding: 12,
              borderRadius: 7,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: t.text, marginBottom: 10 }}>Add Binding</div>
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
          </div>
        )}
      </Section>

      <ConfirmDialog
        open={unbindTarget !== null}
        title="Unbind Integration"
        message={unbindTarget ? `Remove "${unbindTarget.type}" binding (${unbindTarget.clientId})?` : ""}
        confirmLabel="Unbind"
        variant="danger"
        onConfirm={() => {
          if (unbindTarget) unbindMutation.mutate(unbindTarget.id);
          setUnbindTarget(null);
        }}
        onCancel={() => setUnbindTarget(null)}
      />
    </>
  );
}
