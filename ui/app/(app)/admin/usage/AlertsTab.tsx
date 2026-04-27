import {
  BellOff,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Send,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  useSpikeAlertHistory,
  useSpikeConfig,
  useSpikeStatus,
  useTestSpikeAlert,
  useUpdateSpikeConfig,
} from "@/src/api/hooks/useSpikeAlerts";
import { useNotificationTargets } from "@/src/api/hooks/useNotificationTargets";
import { FormRow, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { TraceActionButton } from "@/src/components/shared/TraceActionButton";
import type { SpikeAlert } from "@/src/types/api";

function fmtCost(value: number | null | undefined): string {
  if (value == null) return "--";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function StatusBanner() {
  const { data: status, isLoading } = useSpikeStatus();
  const { data: config } = useSpikeConfig();

  if (isLoading || !status) {
    return (
      <div className="flex items-center justify-center py-5">
        <Spinner />
      </div>
    );
  }

  if (!status.enabled) {
    return (
      <InfoBanner icon={<BellOff size={15} />}>
        Spike alerts are disabled. Enable them below to start monitoring.
      </InfoBanner>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <InfoBanner variant={status.spiking ? "danger" : "success"}>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <StatusBadge label={status.spiking ? "Spike detected" : "Normal"} variant={status.spiking ? "danger" : "success"} />
          {status.spike_ratio != null && <QuietPill label={`${status.spike_ratio.toFixed(1)}x baseline`} />}
          {status.cooldown_active && (
            <QuietPill label={`cooldown ${Math.ceil(status.cooldown_remaining_seconds / 60)}m`} className="text-warning-muted" />
          )}
          {config?.last_check_at && (
            <span className="ml-auto text-[11px] text-text-dim">Checked {fmtRelativeTime(config.last_check_at)}</span>
          )}
        </div>
      </InfoBanner>
      <SettingsStatGrid
        items={[
          { label: "Current rate", value: `${fmtCost(status.window_rate)}/hr`, tone: status.spiking ? "danger" : "success" },
          { label: "Baseline", value: `${fmtCost(status.baseline_rate)}/hr` },
          { label: "Ratio", value: status.spike_ratio != null ? `${status.spike_ratio.toFixed(1)}x` : "--" },
          { label: "Cooldown", value: status.cooldown_active ? `${Math.ceil(status.cooldown_remaining_seconds / 60)}m` : "clear" },
        ]}
      />
    </div>
  );
}

function DebouncedNumberInput({
  value,
  onChange,
  step,
  min,
}: {
  value: number;
  onChange: (value: number) => void;
  step?: string;
  min?: number;
}) {
  const [local, setLocal] = useState(String(value));
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setLocal(String(value)), [value]);

  const flush = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const parsed = step ? parseFloat(local) : parseInt(local, 10);
    if (!Number.isNaN(parsed) && parsed !== value) onChange(parsed);
  }, [local, onChange, step, value]);

  const handleChange = (next: string) => {
    setLocal(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const parsed = step ? parseFloat(next) : parseInt(next, 10);
      if (!Number.isNaN(parsed)) onChange(parsed);
    }, 800);
  };

  return (
    <TextInput
      value={local}
      onChangeText={handleChange}
      onBlur={flush}
      type="number"
      min={min}
      step={step}
    />
  );
}

function ConfigForm() {
  const { data: config, isLoading } = useSpikeConfig();
  const updateConfig = useUpdateSpikeConfig();
  const { data: notificationTargets } = useNotificationTargets();
  const testAlert = useTestSpikeAlert();

  if (isLoading || !config) {
    return (
      <div className="flex items-center justify-center py-5">
        <Spinner />
      </div>
    );
  }

  const availableTargets = (notificationTargets ?? []).filter((target) => target.enabled);
  const selectedTargetIds = config.target_ids || [];
  const handleUpdate = (field: string, value: any) => updateConfig.mutate({ [field]: value });

  const toggleTarget = (targetId: string) => {
    if (selectedTargetIds.includes(targetId)) {
      handleUpdate("target_ids", selectedTargetIds.filter((id) => id !== targetId));
      return;
    }
    handleUpdate("target_ids", [...selectedTargetIds, targetId]);
  };

  return (
    <div className="flex flex-col gap-4 rounded-md bg-surface-raised/35 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <SettingsGroupLabel label="Configuration" />
        {updateConfig.isPending && <span className="text-[11px] text-text-dim">Saving...</span>}
      </div>
      <Toggle
        value={config.enabled}
        onChange={(enabled) => handleUpdate("enabled", enabled)}
        label="Enable spike detection"
        description="Monitor short-window usage against baseline spend and notify configured targets."
      />

      {config.enabled && (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <FormRow label="Window" description="Minutes for current rate">
              <DebouncedNumberInput value={config.window_minutes} min={1} onChange={(value) => handleUpdate("window_minutes", Math.max(1, value))} />
            </FormRow>
            <FormRow label="Baseline" description="Hours of history">
              <DebouncedNumberInput value={config.baseline_hours} min={1} onChange={(value) => handleUpdate("baseline_hours", Math.max(1, value))} />
            </FormRow>
            <FormRow label="Relative threshold" description="Nx baseline">
              <DebouncedNumberInput value={config.relative_threshold} min={0} step="0.1" onChange={(value) => handleUpdate("relative_threshold", Math.max(0, value))} />
            </FormRow>
            <FormRow label="Absolute threshold" description="USD/hour, 0 disables">
              <DebouncedNumberInput value={config.absolute_threshold_usd} min={0} step="0.01" onChange={(value) => handleUpdate("absolute_threshold_usd", Math.max(0, value))} />
            </FormRow>
            <FormRow label="Cooldown" description="Minutes between alerts">
              <DebouncedNumberInput value={config.cooldown_minutes} min={0} onChange={(value) => handleUpdate("cooldown_minutes", Math.max(0, value))} />
            </FormRow>
          </div>

          <div className="flex flex-col gap-2">
            <SettingsGroupLabel label="Alert targets" count={selectedTargetIds.length} />
            {selectedTargetIds.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {selectedTargetIds.map((targetId) => {
                  const target = availableTargets.find((item) => item.id === targetId);
                  return (
                  <button
                    key={targetId}
                    type="button"
                    onClick={() => toggleTarget(targetId)}
                    className="inline-flex min-h-[28px] items-center gap-1.5 rounded-full bg-accent/10 px-2.5 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/15"
                  >
                    {target?.label || targetId}
                    <X size={11} />
                  </button>
                  );
                })}
              </div>
            )}
            {availableTargets.some((target) => !selectedTargetIds.includes(target.id)) && (
              <div className="flex flex-wrap gap-1.5">
                {availableTargets.filter((target) => !selectedTargetIds.includes(target.id)).map((target) => (
                  <ActionButton
                    key={target.id}
                    label={`Add ${target.label}`}
                    size="small"
                    variant="secondary"
                    onPress={() => toggleTarget(target.id)}
                  />
                ))}
              </div>
            )}
            {availableTargets.length === 0 && selectedTargetIds.length === 0 && (
              <EmptyState message="No notification targets found. Create targets in Admin -> Notifications first." />
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              label={testAlert.isPending ? "Sending..." : "Send test alert"}
              variant="secondary"
              icon={<Send size={12} />}
              disabled={testAlert.isPending || selectedTargetIds.length === 0}
              onPress={() => testAlert.mutate()}
            />
            {selectedTargetIds.length === 0 && <span className="text-[11px] text-text-dim">Select at least one target first.</span>}
            {testAlert.data && (
              <span className={`text-[11px] ${testAlert.data.ok ? "text-success" : "text-danger"}`}>
                {testAlert.data.ok
                  ? `Sent: ${testAlert.data.targets_succeeded}/${testAlert.data.targets_attempted}`
                  : "Failed"}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function AlertDetail({ alert }: { alert: SpikeAlert }) {
  return (
    <div className="flex flex-col gap-3 rounded-md bg-surface-overlay/25 px-4 py-3">
      {alert.top_models.length > 0 && (
        <div>
          <SettingsGroupLabel label="Top models" />
          <div className="mt-1 flex flex-col gap-1">
            {alert.top_models.map((model, index) => (
              <div key={index} className="text-[11px] text-text-muted">
                <span className="font-mono text-text">{model.model}</span> · {fmtCost(model.cost)} · {model.calls} calls
              </div>
            ))}
          </div>
        </div>
      )}
      {alert.top_bots.length > 0 && (
        <div>
          <SettingsGroupLabel label="Top bots" />
          <div className="mt-1 flex flex-col gap-1">
            {alert.top_bots.map((bot, index) => (
              <div key={index} className="text-[11px] text-text-muted">
                <span className="font-mono text-text">{bot.bot_id}</span> · {fmtCost(bot.cost)}
              </div>
            ))}
          </div>
        </div>
      )}
      {alert.recent_traces.length > 0 && (
        <div>
          <SettingsGroupLabel label="Recent traces" />
          <div className="mt-1 flex flex-col gap-1">
            {alert.recent_traces.map((trace) => (
              <SettingsControlRow
                key={trace.correlation_id}
                compact
                title={<span className="font-mono">{trace.correlation_id.slice(0, 8)}</span>}
                description={`${trace.model} · ${trace.bot_id} · ${fmtCost(trace.cost)}`}
                action={
                  <TraceActionButton
                    correlationId={trace.correlation_id}
                    title="Spike alert trace"
                    subtitle={trace.bot_id}
                    label="Open"
                    stopPropagation
                  />
                }
              />
            ))}
          </div>
        </div>
      )}
      {alert.delivery_details.length > 0 && (
        <div>
          <SettingsGroupLabel label="Delivery" />
          <div className="mt-1 flex flex-col gap-1">
            {alert.delivery_details.map((delivery, index) => (
              <div key={index} className={delivery.success ? "text-[11px] text-success" : "text-[11px] text-danger"}>
                {delivery.target?.label || delivery.target?.channel_id || delivery.target?.client_id || "unknown"}:{" "}
                {delivery.success ? "OK" : delivery.error || "failed"}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AlertHistory() {
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading } = useSpikeAlertHistory(page);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-5">
        <Spinner />
      </div>
    );
  }

  if (!data || data.alerts.length === 0) {
    return <EmptyState message="No spike alerts have been fired yet." />;
  }

  const totalPages = Math.ceil(data.total / data.page_size);

  return (
    <div className="flex flex-col gap-2">
      <SettingsGroupLabel label="Alert history" count={data.total} />
      <div className="flex flex-col gap-1">
        {data.alerts.map((alert: SpikeAlert) => {
          const open = expanded === alert.id;
          return (
            <div key={alert.id} className="flex flex-col gap-1">
              <SettingsControlRow
                compact
                onClick={() => setExpanded(open ? null : alert.id)}
                title={fmtTime(alert.created_at)}
                description={`${fmtCost(alert.window_rate_usd_per_hour)}/hr · baseline ${fmtCost(alert.baseline_rate_usd_per_hour)}/hr`}
                meta={
                  <div className="flex items-center gap-1.5">
                    <StatusBadge label={alert.trigger_reason} variant="warning" />
                    {alert.spike_ratio != null && <QuietPill label={`${alert.spike_ratio.toFixed(1)}x`} />}
                    <QuietPill label={`${alert.targets_succeeded}/${alert.targets_attempted} delivered`} />
                    {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </div>
                }
              />
              {open && <AlertDetail alert={alert} />}
            </div>
          );
        })}
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-1">
          <ActionButton
            label="Previous"
            size="small"
            variant="secondary"
            icon={<ChevronLeft size={12} />}
            disabled={page <= 1}
            onPress={() => setPage((current) => Math.max(1, current - 1))}
          />
          <span className="text-[12px] text-text-dim">Page {page} of {totalPages}</span>
          <ActionButton
            label="Next"
            size="small"
            variant="secondary"
            icon={<ChevronRight size={12} />}
            disabled={page >= totalPages}
            onPress={() => setPage((current) => Math.min(totalPages, current + 1))}
          />
        </div>
      )}
    </div>
  );
}

export function AlertsTab() {
  return (
    <div className="flex flex-col gap-5">
      <StatusBanner />
      <ConfigForm />
      <AlertHistory />
    </div>
  );
}
