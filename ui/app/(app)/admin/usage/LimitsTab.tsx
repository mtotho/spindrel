import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { useBots } from "@/src/api/hooks/useBots";
import { useUsageForecast, type LimitForecast } from "@/src/api/hooks/useUsageForecast";
import {
  type UsageLimitStatus,
  useCreateUsageLimit,
  useDeleteUsageLimit,
  useUpdateUsageLimit,
  useUsageLimits,
  useUsageLimitsStatus,
} from "@/src/api/hooks/useUsageLimits";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { Col, FormRow, Row, SelectInput, TextInput } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  ActionButton,
  EmptyState,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsMeter,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function fmtCost(value: number | null | undefined): string {
  if (value == null) return "--";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function limitTone(value: number): "success" | "warning" | "danger" | "accent" {
  if (value >= 90) return "danger";
  if (value >= 70) return "warning";
  return "success";
}

function LimitStatusCard({ status, forecast }: { status: UsageLimitStatus; forecast?: LimitForecast }) {
  const projected = forecast?.projected_percentage;
  const tone = limitTone(Math.max(status.percentage, projected ?? 0));

  return (
    <div className="rounded-md bg-surface-raised/40 px-4 py-3">
      <div className="mb-2 flex min-w-0 items-center gap-2">
        <StatusBadge label={status.period} variant={tone === "danger" ? "danger" : tone === "warning" ? "warning" : "success"} />
        <div className="min-w-0 truncate text-[12px] font-semibold text-text">{status.scope_value}</div>
        <div className="ml-auto text-[10px] uppercase tracking-[0.06em] text-text-dim">{status.scope_type}</div>
      </div>
      <div className="mb-2 font-mono text-[16px] font-semibold text-text">
        {fmtCost(status.current_spend)}
        <span className="text-[11px] font-medium text-text-dim"> / {fmtCost(status.limit_usd)}</span>
      </div>
      <SettingsMeter
        value={status.percentage}
        projected={projected}
        tone={tone}
        valueLabel={`${status.percentage}%`}
        projectedLabel={projected != null && projected > status.percentage ? `projected ${projected.toFixed(0)}%` : undefined}
      />
      {forecast && (
        <div className="mt-2 text-[11px] text-text-dim">
          Projected spend: <span className="font-mono text-text-muted">{fmtCost(forecast.projected_spend)}</span>
        </div>
      )}
    </div>
  );
}

function AddLimitForm() {
  const { data: bots } = useBots();
  const createMutation = useCreateUsageLimit();
  const [scopeType, setScopeType] = useState<"model" | "bot">("model");
  const [scopeValue, setScopeValue] = useState("");
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [limitUsd, setLimitUsd] = useState("");

  const botOptions = (bots ?? []).map((bot: any) => ({ label: bot.name || bot.id, value: bot.id as string }));
  const canSubmit = Boolean(scopeValue && limitUsd && !createMutation.isPending);

  const handleSubmit = () => {
    const limit = parseFloat(limitUsd);
    if (!scopeValue || Number.isNaN(limit) || limit <= 0) return;
    createMutation.mutate(
      { scope_type: scopeType, scope_value: scopeValue, period, limit_usd: limit },
      {
        onSuccess: () => {
          setLimitUsd("");
          setScopeValue("");
        },
      },
    );
  };

  return (
    <div className="rounded-md bg-surface-raised/35 px-4 py-3">
      <Row>
        <Col minWidth={150}>
          <FormRow label="Scope">
            <SelectInput
              value={scopeType}
              onChange={(next) => {
                setScopeType(next as "model" | "bot");
                setScopeValue("");
              }}
              options={[
                { label: "Model", value: "model" },
                { label: "Bot", value: "bot" },
              ]}
            />
          </FormRow>
        </Col>
        <Col minWidth={260} flex={2}>
          <FormRow label={scopeType === "model" ? "Model" : "Bot"}>
            {scopeType === "model" ? (
              <LlmModelDropdown
                value={scopeValue}
                onChange={setScopeValue}
                placeholder="Select model..."
                allowClear={false}
              />
            ) : botOptions.length > 0 ? (
              <SelectInput
                value={scopeValue}
                onChange={setScopeValue}
                options={[{ label: "Select bot...", value: "" }, ...botOptions]}
              />
            ) : (
              <TextInput value={scopeValue} onChangeText={setScopeValue} placeholder="Bot ID" />
            )}
          </FormRow>
        </Col>
        <Col minWidth={150}>
          <FormRow label="Period">
            <SelectInput
              value={period}
              onChange={(next) => setPeriod(next as "daily" | "monthly")}
              options={[
                { label: "Daily", value: "daily" },
                { label: "Monthly", value: "monthly" },
              ]}
            />
          </FormRow>
        </Col>
        <Col minWidth={140}>
          <FormRow label="Limit">
            <TextInput
              value={limitUsd}
              onChangeText={setLimitUsd}
              type="number"
              placeholder="0.00"
            />
          </FormRow>
        </Col>
      </Row>
      <div className="mt-3 flex items-center justify-end gap-2">
        {createMutation.isError && (
          <div className="mr-auto text-[12px] text-danger">
            {(createMutation.error as any)?.message || "Failed to create limit"}
          </div>
        )}
        <ActionButton
          label={createMutation.isPending ? "Adding..." : "Add limit"}
          icon={<Plus size={12} />}
          disabled={!canSubmit}
          onPress={handleSubmit}
        />
      </div>
    </div>
  );
}

function LimitsList() {
  const { data: limits, isLoading } = useUsageLimits();
  const updateMutation = useUpdateUsageLimit();
  const deleteMutation = useDeleteUsageLimit();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  if (isLoading) return <Spinner />;
  if (!limits || limits.length === 0) {
    return <EmptyState message="No limits configured." />;
  }

  return (
    <div className="flex flex-col gap-1">
      {limits.map((limit) => (
        <SettingsControlRow
          key={limit.id}
          compact
          className={limit.enabled ? "" : "opacity-55"}
          title={limit.scope_value}
          description={`${limit.scope_type} · ${limit.period}`}
          meta={
            <div className="font-mono text-[11px] text-text-muted">
              ${limit.limit_usd.toFixed(2)}
            </div>
          }
          action={
            <div className="flex items-center gap-1">
              <ActionButton
                label={limit.enabled ? "On" : "Off"}
                size="small"
                variant={limit.enabled ? "primary" : "secondary"}
                onPress={() => updateMutation.mutate({ id: limit.id, enabled: !limit.enabled })}
              />
              <ActionButton
                label="Delete"
                size="small"
                variant="danger"
                icon={<Trash2 size={12} />}
                onPress={async () => {
                  const ok = await confirm("Delete this limit?", {
                    title: "Delete limit",
                    confirmLabel: "Delete",
                    variant: "danger",
                  });
                  if (ok) deleteMutation.mutate(limit.id);
                }}
              />
            </div>
          }
        />
      ))}
      <ConfirmDialogSlot />
    </div>
  );
}

export function LimitsTab({ knownModels: _knownModels }: { knownModels: string[] }) {
  const { data: statuses, isLoading } = useUsageLimitsStatus();
  const { data: forecast } = useUsageForecast();

  const findForecast = (status: UsageLimitStatus): LimitForecast | undefined =>
    forecast?.limits.find(
      (limit) =>
        limit.scope_type === status.scope_type &&
        limit.scope_value === status.scope_value &&
        limit.period === status.period,
    );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Active guardrails" count={statuses?.length ?? 0} />
        {isLoading ? (
          <Spinner />
        ) : statuses && statuses.length > 0 ? (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {statuses.map((status) => (
              <LimitStatusCard key={status.id} status={status} forecast={findForecast(status)} />
            ))}
          </div>
        ) : (
          <EmptyState message="No active limit status yet. Add a limit to start tracking spend guardrails." />
        )}
      </div>
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Add limit" />
        <AddLimitForm />
      </div>
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="All limits" />
        <LimitsList />
      </div>
    </div>
  );
}
