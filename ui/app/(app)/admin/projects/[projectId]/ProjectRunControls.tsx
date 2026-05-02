import { Link } from "react-router-dom";
import { ExternalLink, ServerCog } from "lucide-react";

import { useTaskMachineAutomationOptions, type MachineTargetGrant } from "@/src/api/hooks/useTasks";
import { FormRow, SelectInput } from "@/src/components/shared/FormControls";
import type { ProjectCodingRun } from "@/src/types/api";

export function RowLink({ to, href, children }: { to?: string; href?: string; children: React.ReactNode }) {
  const className = "inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text";
  const content = (
    <>
      <ExternalLink size={13} />
      {children}
    </>
  );
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className}>
        {content}
      </a>
    );
  }
  return (
    <Link to={to ?? "#"} className={className}>
      {content}
    </Link>
  );
}

export function formatRunTime(value?: string | null) {
  if (!value) return "No timestamp";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

const START_OFFSET_MS: Record<string, number> = {
  s: 1000,
  m: 60_000,
  h: 3_600_000,
  d: 86_400_000,
  w: 604_800_000,
};

function toLocalDateTimeInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function scheduledAtForPicker(value: string | null | undefined): string {
  if (!value) return "";
  const match = value.match(/^\+(\d+)([smhdw])$/);
  if (!match) return value;
  const amount = Number.parseInt(match[1], 10);
  const unit = match[2];
  const ms = amount * (START_OFFSET_MS[unit] ?? 0);
  return toLocalDateTimeInput(new Date(Date.now() + ms));
}

export function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "completed" || status === "complete" || status === "reported" || status === "ready_for_review" || status === "reviewed") return "success";
  if (status === "pending" || status === "running" || status === "needs_review" || status === "pending_evidence" || status === "missing_evidence" || status === "follow_up_running" || status === "follow_up_created" || status === "reviewing") return "warning";
  if (status === "failed" || status === "blocked" || status === "setup_blocked" || status === "changes_requested") return "danger";
  return "neutral";
}

export function executionAccessLine(grant?: ProjectCodingRun["task"]["machine_target_grant"]) {
  if (!grant) return null;
  const target = grant.target_label || grant.target_id;
  const provider = grant.provider_label || grant.provider_id;
  const capabilities = grant.capabilities?.length ? grant.capabilities.join(", ") : "target";
  return `${provider}: ${target} · ${capabilities}${grant.allow_agent_tools === false ? " · tools off" : ""}`;
}

export function ExecutionAccessControl({
  value,
  onChange,
  testId,
}: {
  value: MachineTargetGrant | null;
  onChange: (next: MachineTargetGrant | null) => void;
  testId: string;
}) {
  const { data: machineAutomation } = useTaskMachineAutomationOptions();
  const providers = machineAutomation?.providers ?? [];
  const targetOptions = [
    { label: "No machine target", value: "" },
    ...providers.flatMap((provider) =>
      (provider.targets ?? []).map((target) => ({
        label: `${provider.provider_label || provider.label}: ${target.label || target.target_id}${target.ready ? "" : " (not ready)"}`,
        value: JSON.stringify([provider.provider_id, target.target_id]),
      })),
    ),
  ];
  if (
    value?.target_id
    && !targetOptions.some((option) => {
      try {
        const [providerId, targetId] = JSON.parse(option.value);
        return providerId === value.provider_id && targetId === value.target_id;
      } catch {
        return false;
      }
    })
  ) {
    targetOptions.push({
      label: `${value.provider_label || value.provider_id}: ${value.target_label || value.target_id}`,
      value: JSON.stringify([value.provider_id, value.target_id]),
    });
  }
  const selectedValue = value ? JSON.stringify([value.provider_id, value.target_id]) : "";
  const selectedProvider = providers.find((provider) => provider.provider_id === value?.provider_id);
  const selectedTarget = selectedProvider?.targets?.find((target) => target.target_id === value?.target_id);
  const allowedCapabilities = selectedTarget?.capabilities?.length
    ? selectedTarget.capabilities
    : selectedProvider?.capabilities?.length
      ? selectedProvider.capabilities
      : value?.capabilities?.length
        ? value.capabilities
        : ["inspect"];
  const selectedCapabilities = new Set(value?.capabilities?.length ? value.capabilities : allowedCapabilities);
  const showControl = targetOptions.length > 1 || !!value;
  if (!showControl) return null;

  const updateCapability = (capability: string, checked: boolean) => {
    if (!value) return;
    const next = new Set(selectedCapabilities);
    if (checked) next.add(capability);
    else next.delete(capability);
    const capabilities = allowedCapabilities.filter((item) => next.has(item));
    onChange({
      ...value,
      capabilities: capabilities.length > 0 ? capabilities : [allowedCapabilities[0] || "inspect"],
    });
  };

  return (
    <div data-testid={testId} className="rounded-md bg-surface-raised/30 px-3 py-3">
      <div className="mb-3 flex items-start gap-2">
        <ServerCog size={14} className="mt-0.5 shrink-0 text-text-dim" />
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-text">Execution access</div>
          <div className="text-[12px] text-text-muted">Task-scoped existing target grant for e2e, screenshots, and server checks.</div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(220px,0.9fr)_minmax(0,1.1fr)]">
        <FormRow label="Target">
          <SelectInput
            value={selectedValue}
            onChange={(encodedTarget) => {
              if (!encodedTarget) {
                onChange(null);
                return;
              }
              try {
                const [providerId, targetId] = JSON.parse(encodedTarget);
                const provider = providers.find((item) => item.provider_id === providerId);
                const target = provider?.targets?.find((item) => item.target_id === targetId);
                const capabilities = target?.capabilities?.length
                  ? target.capabilities
                  : provider?.capabilities?.length
                    ? provider.capabilities
                    : ["inspect"];
                onChange({
                  provider_id: providerId,
                  target_id: targetId,
                  capabilities,
                  allow_agent_tools: value?.allow_agent_tools ?? true,
                });
              } catch {
                onChange(null);
              }
            }}
            options={targetOptions}
          />
        </FormRow>
        <div className="flex flex-col gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Capabilities</div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-text-muted">
            {allowedCapabilities.map((capability) => (
              <label key={capability} className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-input-border bg-input"
                  checked={selectedCapabilities.has(capability)}
                  disabled={!value}
                  onChange={(event) => updateCapability(capability, event.target.checked)}
                />
                {capability}
              </label>
            ))}
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input-border bg-input"
                checked={value?.allow_agent_tools ?? true}
                disabled={!value}
                onChange={(event) => value && onChange({ ...value, allow_agent_tools: event.target.checked })}
              />
              Agent tools
            </label>
          </div>
          <div className="text-[11px] text-text-dim">
            {value ? "Grant is attached only to the task being launched." : "No machine access is granted unless a target is selected."}
          </div>
        </div>
      </div>
    </div>
  );
}
