import { useState } from "react";
import { Plus, Pencil, X } from "lucide-react";
import {
  useChannelIntegrations,
  useAvailableIntegrations,
  useBindIntegration,
  useUnbindIntegration,
} from "@/src/api/hooks/useChannels";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { configSummaryText } from "./helpers";
import { BindingForm } from "./BindingForm";

export function BindingsSection({ channelId }: { channelId: string }) {
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
        <div className="flex items-center gap-2 p-3">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      </Section>
    );
  }

  const visibleBindings = (bindings ?? []).filter((b) => !b.client_id.startsWith("mc-activated:"));

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
        {visibleBindings.length === 0 ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <div className="flex flex-col gap-2">
            {visibleBindings.map((b) => {
              const dc = b.dispatch_config ?? {};
              const summary = configSummaryText(dc, available.find((a) => a.type === b.integration_type)?.binding?.config_fields);
              if (editingId === b.id) {
                return (
                  <div
                    key={b.id}
                    className="rounded-md bg-surface-raised/35 p-3.5"
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
                );
              }
              return (
                <SettingsControlRow
                  key={b.id}
                  className="flex flex-wrap items-center gap-3"
                >
                  <StatusBadge label={b.integration_type} variant="info" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-text">
                      {b.client_id}
                    </div>
                    {b.display_name && (
                      <div className="mt-0.5 truncate text-[11px] text-text-dim">
                        {b.display_name}
                      </div>
                    )}
                    {summary && (
                      <div className="mt-0.5 text-[10px] text-text-dim">
                        {summary}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionButton
                      label="Edit"
                      onPress={() => setEditingId(b.id)}
                      variant="secondary"
                      size="small"
                      icon={<Pencil size={12} />}
                    />
                    <ActionButton
                      label="Remove"
                      onPress={() => setUnbindTarget({ id: b.id, type: b.integration_type, clientId: b.client_id })}
                      variant="danger"
                      size="small"
                      icon={<X size={12} />}
                    />
                  </div>
                </SettingsControlRow>
              );
            })}
          </div>
        )}
        {showAdd && (
          <div className="mt-3 rounded-md bg-surface-raised/35 p-3.5">
            <div className="mb-2.5 text-[12px] font-semibold text-text tracking-[-0.01em]">Add Binding</div>
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
