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
import { FormRow, TextInput } from "@/src/components/shared/FormControls";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import type { NotificationDestination, NotificationTarget } from "@/src/types/api";

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

function TargetRow({ target, targets }: { target: NotificationTarget; targets: NotificationTarget[] }) {
  const update = useUpdateNotificationTarget();
  const remove = useDeleteNotificationTarget();
  const test = useTestNotificationTarget();
  const { data: bots } = useAdminBots();
  const botList = bots ?? [];
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
    <div className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-raised/35 px-4 py-3">
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
        {botList.length === 0 ? (
          <div className="text-[11px] text-text-dim">No bots found.</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {botList.map((bot) => {
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
  const options = destinations?.options ?? [];
  const existingKeys = useMemo(() => new Set(targets.map((t) => `${t.kind}:${JSON.stringify(t.config)}`)), [targets]);

  const createFromDestination = (option: NotificationDestination) => {
    create.mutate({
      label: option.label,
      kind: option.kind,
      config: option.config,
      allowed_bot_ids: [],
      enabled: true,
    });
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
    <div className="flex flex-col gap-3 rounded-md bg-surface-raised/35 px-4 py-3">
      <SettingsGroupLabel label="Create targets" />
      {isLoading ? (
        <Spinner />
      ) : options.length === 0 ? (
        <EmptyState message="No push subscriptions, channels, or integration bindings are available yet." />
      ) : (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {options.map((option, index) => {
            const exists = existingKeys.has(`${option.kind}:${JSON.stringify(option.config)}`);
            return (
              <SettingsControlRow
                key={`${option.kind}-${index}`}
                compact
                title={option.label}
                description={`${option.kind.replace("_", " ")}${option.description ? ` · ${option.description}` : ""}`}
                meta={
                  <ActionButton
                    size="small"
                    variant="secondary"
                    icon={<Plus size={12} />}
                    label={exists ? "Exists" : "Add"}
                    disabled={exists || create.isPending}
                    onPress={() => createFromDestination(option)}
                  />
                }
              />
            );
          })}
        </div>
      )}
      <div className="flex flex-wrap items-end gap-2 border-t border-border-subtle pt-3">
        <div className="min-w-[260px] flex-1">
          <FormRow label="Group target">
            <TextInput value={groupName} onChangeText={setGroupName} placeholder="Ops alerts" />
          </FormRow>
        </div>
        <ActionButton icon={<Plus size={12} />} label="Create group" disabled={!groupName.trim()} onPress={createGroup} />
      </div>
    </div>
  );
}

function DeliveryHistory() {
  const { data, isLoading } = useNotificationDeliveries();
  if (isLoading) return <Spinner />;
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
  const rows = targets ?? [];

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-4 md:p-6">
      <PageHeader
        variant="list"
        title="Notifications"
        subtitle="Reusable targets for alerts, bots, and automations."
      />
      <CreateTargetPanel targets={rows} />
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Targets" count={rows.length} />
        {isLoading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <EmptyState message="Create a notification target to grant it to bots or use it from usage alerts." />
        ) : (
          rows.map((target) => <TargetRow key={target.id} target={target} targets={rows} />)
        )}
      </div>
      <DeliveryHistory />
    </div>
  );
}
