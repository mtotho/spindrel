import { Spinner } from "@/src/components/shared/Spinner";
import { useState } from "react";

import { Trash2 } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useUsageLimits,
  useUsageLimitsStatus,
  useCreateUsageLimit,
  useUpdateUsageLimit,
  useDeleteUsageLimit,
  type UsageLimitStatus,
} from "@/src/api/hooks/useUsageLimits";
import { useUsageForecast, type LimitForecast } from "@/src/api/hooks/useUsageForecast";
import { useThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function progressColor(pct: number, t: ReturnType<typeof useThemeTokens>): string {
  if (pct >= 90) return t.danger;
  if (pct >= 70) return t.warning;
  return t.success;
}

/** Shared input style matching LlmModelDropdown's trigger (7px 12px, border-radius 8). */
function useInputStyle(): React.CSSProperties {
  const t = useThemeTokens();
  return {
    background: t.inputBg,
    color: t.text,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 8,
    padding: "7px 12px",
    fontSize: 13,
    outline: "none",
    height: 36,
    boxSizing: "border-box" as const,
  };
}

// ---------------------------------------------------------------------------
// Status cards
// ---------------------------------------------------------------------------

function LimitStatusCard({ s, forecast }: { s: UsageLimitStatus; forecast?: LimitForecast }) {
  const t = useThemeTokens();
  const color = progressColor(s.percentage, t);
  const projPct = forecast?.projected_percentage;
  const projColor = projPct != null ? progressColor(projPct, t) : undefined;

  return (
    <div
      style={{
        flex: 1,
        minWidth: 200,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: "14px 16px",
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {s.scope_type} &middot; {s.period}
        </div>
        <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 600, color }}>{s.percentage}%</span>
          {projPct != null && projPct > s.percentage && (
            <span style={{ fontSize: 10, color: projColor }}>
              → {projPct.toFixed(0)}%
            </span>
          )}
        </div>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
        {s.scope_value}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: t.text, fontFamily: "monospace", marginBottom: 2 }}>
        {fmtCost(s.current_spend)}
        <span style={{ fontSize: 12, fontWeight: 400, color: t.textMuted }}> / {fmtCost(s.limit_usd)}</span>
      </div>
      {forecast && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 6 }}>
          Projected: {fmtCost(forecast.projected_spend)}
        </div>
      )}
      {/* Dual progress bar: solid for current, striped extension for projected */}
      <div
        style={{
          height: 4,
          borderRadius: 2,
          background: t.surfaceBorder,
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Projected extension (behind, wider) */}
        {projPct != null && projPct > s.percentage && (
          <div
            style={{
              position: "absolute",
              height: "100%",
              width: `${Math.min(projPct, 100)}%`,
              background: projColor,
              borderRadius: 2,
              opacity: 0.3,
              transition: "width 0.3s ease",
            }}
          />
        )}
        {/* Current (solid, on top) */}
        <div
          style={{
            position: "relative",
            height: "100%",
            width: `${Math.min(s.percentage, 100)}%`,
            background: color,
            borderRadius: 2,
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Limit form
// ---------------------------------------------------------------------------

function AddLimitForm({ knownModels }: { knownModels: string[] }) {
  const t = useThemeTokens();
  const inputStyle = useInputStyle();
  const { data: bots } = useBots();
  const createMutation = useCreateUsageLimit();

  const [scopeType, setScopeType] = useState<"model" | "bot">("model");
  const [scopeValue, setScopeValue] = useState("");
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [limitUsd, setLimitUsd] = useState("");

  const handleSubmit = () => {
    const val = parseFloat(limitUsd);
    if (!scopeValue || isNaN(val) || val <= 0) return;
    createMutation.mutate(
      { scope_type: scopeType, scope_value: scopeValue, period, limit_usd: val },
      { onSuccess: () => { setLimitUsd(""); setScopeValue(""); } },
    );
  };

  const botOptions = (bots ?? []).map((b: any) => b.id as string);
  const canSubmit = !!scopeValue && !!limitUsd && !createMutation.isPending;

  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "flex-end",
      }}
    >
      {/* Scope type */}
      <div style={{ minWidth: 90 }}>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Type</div>
        <select
          value={scopeType}
          onChange={(e) => { setScopeType(e.target.value as any); setScopeValue(""); }}
          style={inputStyle}
        >
          <option value="model">Model</option>
          <option value="bot">Bot</option>
        </select>
      </div>

      {/* Scope value — LlmModelDropdown for models, select for bots */}
      <div style={{ minWidth: 200, flex: 1 }}>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>
          {scopeType === "model" ? "Model" : "Bot"}
        </div>
        {scopeType === "model" ? (
          <LlmModelDropdown
            value={scopeValue}
            onChange={setScopeValue}
            placeholder="Select model..."
            allowClear={false}
          />
        ) : botOptions.length > 0 ? (
          <select value={scopeValue} onChange={(e) => setScopeValue(e.target.value)} style={{ ...inputStyle, width: "100%" }}>
            <option value="">Select bot...</option>
            {botOptions.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input
            value={scopeValue}
            onChange={(e) => setScopeValue(e.target.value)}
            placeholder="Bot ID"
            style={{ ...inputStyle, width: "100%" }}
          />
        )}
      </div>

      {/* Period */}
      <div style={{ minWidth: 90 }}>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Period</div>
        <select value={period} onChange={(e) => setPeriod(e.target.value as any)} style={inputStyle}>
          <option value="daily">Daily</option>
          <option value="monthly">Monthly</option>
        </select>
      </div>

      {/* Limit USD */}
      <div style={{ minWidth: 80 }}>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>Limit ($)</div>
        <input
          type="number"
          min="0"
          step="0.01"
          value={limitUsd}
          onChange={(e) => setLimitUsd(e.target.value)}
          placeholder="0.00"
          style={{ ...inputStyle, width: "100%" }}
        />
      </div>

      {/* Submit */}
      <div>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          style={{
            height: 36,
            padding: "0 16px",
            fontSize: 13,
            fontWeight: 600,
            background: canSubmit ? t.accent : t.surfaceRaised,
            color: canSubmit ? "#fff" : t.textDim,
            border: `1px solid ${canSubmit ? t.accent : t.surfaceBorder}`,
            borderRadius: 8,
            cursor: canSubmit ? "pointer" : "default",
            boxSizing: "border-box" as const,
          }}
        >
          {createMutation.isPending ? "Adding..." : "Add Limit"}
        </button>
      </div>

      {createMutation.isError && (
        <div style={{ width: "100%", color: t.danger, fontSize: 12 }}>
          {(createMutation.error as any)?.message || "Failed to create"}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Limits list
// ---------------------------------------------------------------------------

function LimitsTable() {
  const t = useThemeTokens();
  const { data: limits, isLoading } = useUsageLimits();
  const updateMutation = useUpdateUsageLimit();
  const deleteMutation = useDeleteUsageLimit();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  if (isLoading) return <Spinner />;
  if (!limits || limits.length === 0) {
    return (
      <div style={{ color: t.textDim, fontSize: 12, marginTop: 8 }}>
        No limits configured.
      </div>
    );
  }

  return (
    <div style={{ border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8, overflow: "hidden" }}>
      {/* Header */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          gap: 12,
          padding: "8px 12px",
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          textTransform: "uppercase",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          background: t.surfaceOverlay,
        }}
      >
        <span style={{ width: 60 }}>Scope</span>
        <span style={{ flex: 1, minWidth: 0 }}>Value</span>
        <span style={{ width: 60 }}>Period</span>
        <span style={{ width: 70, textAlign: "right" }}>Limit</span>
        <span style={{ width: 50, textAlign: "center" }}>Active</span>
        <span style={{ width: 30 }}></span>
      </div>
      {limits.map((lim, i) => (
        <div
          key={lim.id}
          style={{
            display: "flex", flexDirection: "row",
            gap: 12,
            padding: "7px 12px",
            fontSize: 12,
            borderBottom: i < limits.length - 1 ? `1px solid ${t.surfaceRaised}` : "none",
            alignItems: "center",
            opacity: lim.enabled ? 1 : 0.5,
          }}
        >
          <span style={{ width: 60, color: t.textMuted }}>{lim.scope_type}</span>
          <span style={{ flex: 1, minWidth: 0, color: t.text, fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {lim.scope_value}
          </span>
          <span style={{ width: 60, color: t.textMuted }}>{lim.period}</span>
          <span style={{ width: 70, textAlign: "right", color: t.text, fontFamily: "monospace" }}>
            ${lim.limit_usd.toFixed(2)}
          </span>
          <span style={{ width: 50, textAlign: "center" }}>
            <button
              onClick={() => updateMutation.mutate({ id: lim.id, enabled: !lim.enabled })}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: 12,
                color: lim.enabled ? t.success : t.textDim,
                padding: 0,
                fontWeight: 500,
              }}
            >
              {lim.enabled ? "on" : "off"}
            </button>
          </span>
          <span style={{ width: 30, textAlign: "center" }}>
            <button
              onClick={async () => {
                const ok = await confirm("Delete this limit?", {
                  title: "Delete limit",
                  confirmLabel: "Delete",
                  variant: "danger",
                });
                if (ok) deleteMutation.mutate(lim.id);
              }}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: t.textDim,
                padding: 2,
              }}
              title="Delete"
            >
              <Trash2 size={13} />
            </button>
          </span>
        </div>
      ))}
      <ConfirmDialogSlot />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export function LimitsTab({ knownModels }: { knownModels: string[] }) {
  const t = useThemeTokens();
  const { data: statuses, isLoading } = useUsageLimitsStatus();
  const { data: forecast } = useUsageForecast();

  // Match forecast limits to status cards by scope_type + scope_value + period
  const findForecast = (s: UsageLimitStatus): LimitForecast | undefined =>
    forecast?.limits.find(
      (lf) => lf.scope_type === s.scope_type && lf.scope_value === s.scope_value && lf.period === s.period,
    );

  return (
    <div>
      {/* Status cards */}
      {isLoading ? (
        <Spinner />
      ) : statuses && statuses.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 20 }}>
          {statuses.map((s) => (
            <LimitStatusCard key={s.id} s={s} forecast={findForecast(s)} />
          ))}
        </div>
      ) : null}

      {/* Add limit */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>Add Limit</div>
        <AddLimitForm knownModels={knownModels} />
      </div>

      {/* All limits */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>All Limits</div>
        <LimitsTable />
      </div>
    </div>
  );
}
