import { Check, Plus, Send, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import {
  useCreateNotificationTarget,
  useDeleteNotificationTarget,
  useNotificationDeliveries,
  useNotificationDestinations,
  useNotificationTargets,
  useTestNotificationTarget,
  useUpdateNotificationTarget,
} from "@/src/api/hooks/useNotificationTargets";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, SelectInput, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import type { BotConfig, NotificationDestination, NotificationTarget, NotificationTargetKind } from "@/src/types/api";

function fmtTime(iso: string | null | undefined) {
  if (!iso) return "--";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function targetSubtitle(target: NotificationTarget) {
  if (target.kind === "user_push") return target.config.user_id || "push";
  if (target.kind === "channel") return target.config.channel_id || "channel";
  if (target.kind === "integration_binding") return `${target.config.integration_type || "integration"} · ${target.config.client_id || ""}`;
  return `${(target.config.target_ids || []).length} targets`;
}

function destinationHelp(kind: NotificationTargetKind, count: number) {
  if (count > 0) return null;
  if (kind === "user_push") {
    return "PWA push targets appear after a user enables push in Settings -> Account -> Preferences on this server.";
  }
  if (kind === "channel") {
    return "Channel targets appear after channels exist.";
  }
  return "Integration binding targets appear after an integration binding exposes dispatch metadata.";
}

function TargetRow({
  target,
  targets,
  bots,
}: {
  target: NotificationTarget;
  targets: NotificationTarget[];
  bots: BotConfig[];
}) {
  const update = useUpdateNotificationTarget();
  const remove = useDeleteNotificationTarget();
  const test = useTestNotificationTarget();
  const childTargets = targets.filter((item) => item.id !== target.id);

  const toggleBot = (botId: string) => {
    const allowed = target.allowed_bot_ids || [];
    update.mutate({
      id: target.id,
      body: { allowed_bot_ids: allowed.includes(botId) ? allowed.filter((id) => id !== botId) : [...allowed, botId] },
    });
  };

  const toggleChild = (childId: string) => {
    const ids = (target.config.target_ids || []) as string[];
    update.mutate({
      id: target.id,
      body: { config: { ...target.config, target_ids: ids.includes(childId) ? ids.filter((id) => id !== childId) : [...ids, childId] } },
    });
  };

  return (
    <div className="flex flex-col gap-3 rounded-md bg-surface-raised/30 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-[14px] font-semibold text-text">{target.label}</h3>
            <StatusBadge label={target.kind.replace("_", " ")} variant={target.enabled ? "success" : "neutral"} />
            {!target.enabled && <QuietPill label="disabled" />}
          </div>
          <div className="mt-1 text-[11px] text-text-dim">{targetSubtitle(target)}</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <ActionButton
            size="small"
            variant="secondary"
            icon={<Send size={12} />}
            label={test.isPending ? "Sending..." : "Test"}
            disabled={!target.enabled || test.isPending}
            onPress={() => test.mutate(target.id)}
          />
          <ActionButton
            size="small"
            variant="ghost"
            icon={target.enabled ? <X size={12} /> : <Check size={12} />}
            label={target.enabled ? "Disable" : "Enable"}
            onPress={() => update.mutate({ id: target.id, body: { enabled: !target.enabled } })}
          />
          <ActionButton
            size="small"
            variant="danger"
            icon={<Trash2 size={12} />}
            label="Delete"
            onPress={() => remove.mutate(target.id)}
          />
        </div>
      </div>

      {target.kind === "group" && (
        <div className="flex flex-col gap-1">
          <SettingsGroupLabel label="Group members" />
          <div className="flex flex-wrap gap-1.5">
            {childTargets.map((child) => {
              const selected = ((target.config.target_ids || []) as string[]).includes(child.id);
              return (
                <button
                  key={child.id}
                  type="button"
                  onClick={() => toggleChild(child.id)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${selected ? "bg-accent/15 text-accent" : "bg-surface-overlay/40 text-text-muted hover:text-text"}`}
                >
                  {child.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <SettingsGroupLabel label="Bot grants" count={(target.allowed_bot_ids || []).length} />
        {bots.length === 0 ? (
          <div className="text-[11px] text-text-dim">No bots found.</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {bots.map((bot) => {
              const selected = (target.allowed_bot_ids || []).includes(bot.id);
              return (
                <button
                  key={bot.id}
                  type="button"
                  onClick={() => toggleBot(bot.id)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${selected ? "bg-success/15 text-success" : "bg-surface-overlay/40 text-text-muted hover:text-text"}`}
                >
                  {bot.name || bot.id}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function CreateTargetPanel({ targets }: { targets: NotificationTarget[] }) {
  const { data: destinations, isLoading } = useNotificationDestinations();
  const create = useCreateNotificationTarget();
  const [groupName, setGroupName] = useState("");
  const [kind, setKind] = useState<NotificationTargetKind>("user_push");
  const [selectedKey, setSelectedKey] = useState("");
  const options = destinations?.options ?? [];
  const existingKeys = useMemo(() => new Set(targets.map((t) => `${t.kind}:${JSON.stringify(t.config)}`)), [targets]);
  const optionsForKind = options.filter((option) => option.kind === kind);
  const destinationOptions = optionsForKind.map((option, index) => ({
    label: `${option.label}${option.description ? ` - ${option.description}` : ""}`,
    value: String(index),
  }));
  const selectedDestination = selectedKey ? optionsForKind[Number(selectedKey)] : null;
  const selectedExists = selectedDestination
    ? existingKeys.has(`${selectedDestination.kind}:${JSON.stringify(selectedDestination.config)}`)
    : false;
  const helpText = destinationHelp(kind, optionsForKind.length);

  const createFromDestination = (option: NotificationDestination) => {
    create.mutate({
      label: option.label,
      kind: option.kind,
      config: option.config,
      allowed_bot_ids: [],
      enabled: true,
    });
    setSelectedKey("");
  };

  const createGroup = () => {
    if (!groupName.trim()) return;
    create.mutate({
      label: groupName.trim(),
      kind: "group",
      config: { target_ids: [] },
      allowed_bot_ids: [],
      enabled: true,
    });
    setGroupName("");
  };

  return (
    <section className="flex flex-col gap-3 pb-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SettingsGroupLabel label="Create targets" />
        {isLoading && <span className="text-[11px] font-medium text-text-dim">Loading destinations...</span>}
      </div>
      {!isLoading && options.length === 0 ? (
        <EmptyState message="No push subscriptions, channels, or integration bindings are available yet." />
      ) : (
        <div className="grid gap-3 lg:grid-cols-[220px_minmax(0,1fr)_auto] lg:items-end">
          <FormRow label="Kind">
            <SelectInput
              value={kind}
              onChange={(next) => {
                setKind(next as NotificationTargetKind);
                setSelectedKey("");
              }}
              options={[
                { label: "PWA push", value: "user_push" },
                { label: "Channel", value: "channel" },
                { label: "Integration binding", value: "integration_binding" },
              ]}
            />
          </FormRow>
          <FormRow label="Destination">
            <SelectInput
              value={selectedKey}
              onChange={setSelectedKey}
              options={destinationOptions.length > 0 ? destinationOptions : [{ label: "No destinations available", value: "" }]}
            />
          </FormRow>
          <ActionButton
            icon={<Plus size={12} />}
            label={selectedExists ? "Exists" : "Add target"}
            disabled={!selectedDestination || selectedExists || create.isPending}
            onPress={() => selectedDestination && createFromDestination(selectedDestination)}
          />
          {helpText && (
            <div className="text-[11px] leading-relaxed text-text-dim lg:col-start-2">
              {helpText}
            </div>
          )}
        </div>
      )}
      <div className="grid gap-3 pt-1 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-[260px] flex-1">
          <FormRow label="Group target">
            <TextInput value={groupName} onChangeText={setGroupName} placeholder="Ops alerts" />
          </FormRow>
        </div>
        <ActionButton icon={<Plus size={12} />} label="Create group" disabled={!groupName.trim()} onPress={createGroup} />
      </div>
    </section>
  );
}

function DeliveryHistory() {
  const { data, isLoading } = useNotificationDeliveries();
  if (isLoading) return <div className="text-[12px] text-text-dim">Loading delivery history...</div>;
  if (!data || data.deliveries.length === 0) return <EmptyState message="No notification deliveries yet." />;
  return (
    <div className="flex flex-col gap-2">
      <SettingsGroupLabel label="Delivery history" count={data.total} />
      {data.deliveries.map((delivery) => (
        <SettingsControlRow
          key={delivery.id}
          compact
          title={delivery.title}
          description={`${delivery.sender_type}${delivery.sender_id ? ` · ${delivery.sender_id}` : ""} · ${fmtTime(delivery.created_at)}`}
          meta={<QuietPill label={`${delivery.succeeded}/${delivery.attempts}`} />}
        />
      ))}
    </div>
  );
}

export default function AdminNotificationsPage() {
  const { data: targets, isLoading } = useNotificationTargets();
  const { data: bots } = useAdminBots();
  const rows = targets ?? [];
  const botRows = bots ?? [];

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="Notifications"
        subtitle="Reusable targets for alerts, bots, and automations."
      />
      <div className="scroll-subtle min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-4 md:px-8 md:py-5">
          <CreateTargetPanel targets={rows} />
          <div className="flex flex-col gap-2">
            <SettingsGroupLabel label="Targets" count={rows.length} />
            {isLoading ? (
              <div className="text-[12px] text-text-dim">Loading targets...</div>
            ) : rows.length === 0 ? (
              <EmptyState message="Create a notification target to grant it to bots or use it from usage alerts." />
            ) : (
              rows.map((target) => <TargetRow key={target.id} target={target} targets={rows} bots={botRows} />)
            )}
          </div>
          <DeliveryHistory />
        </div>
      </div>
    </div>
  );
}
