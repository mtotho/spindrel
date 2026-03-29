import { useState } from "react";
import { View, ActivityIndicator } from "react-native";
import { Trash2 } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useUsageLimits,
  useUsageLimitsStatus,
  useCreateUsageLimit,
  useUpdateUsageLimit,
  useDeleteUsageLimit,
  type UsageLimitStatus,
  type UsageLimit,
} from "@/src/api/hooks/useUsageLimits";
import { useThemeTokens } from "@/src/theme/tokens";

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

// Matches useSelectStyle() from the parent page
function useSelectStyle(): React.CSSProperties {
  const t = useThemeTokens();
  return {
    background: t.surfaceRaised,
    color: t.textMuted,
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 6,
    padding: "5px 10px",
    fontSize: 12,
    outline: "none",
  };
}

// ---------------------------------------------------------------------------
// Status cards
// ---------------------------------------------------------------------------

function LimitStatusCard({ s }: { s: UsageLimitStatus }) {
  const t = useThemeTokens();
  const color = progressColor(s.percentage, t);
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {s.scope_type} &middot; {s.period}
        </div>
        <span style={{ fontSize: 11, fontWeight: 600, color }}>{s.percentage}%</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
        {s.scope_value}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: t.text, fontFamily: "monospace", marginBottom: 8 }}>
        {fmtCost(s.current_spend)}
        <span style={{ fontSize: 12, fontWeight: 400, color: t.textMuted }}> / {fmtCost(s.limit_usd)}</span>
      </div>
      <div
        style={{
          height: 4,
          borderRadius: 2,
          background: t.surfaceBorder,
          overflow: "hidden",
        }}
      >
        <div
          style={{
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
  const selectStyle = useSelectStyle();
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

  const scopeOptions =
    scopeType === "model"
      ? knownModels
      : (bots ?? []).map((b: any) => b.id);

  const canSubmit = !!scopeValue && !!limitUsd && !createMutation.isPending;

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center",
      }}
    >
      <select
        value={scopeType}
        onChange={(e) => { setScopeType(e.target.value as any); setScopeValue(""); }}
        style={selectStyle}
      >
        <option value="model">Model</option>
        <option value="bot">Bot</option>
      </select>

      {scopeOptions.length > 0 ? (
        <select value={scopeValue} onChange={(e) => setScopeValue(e.target.value)} style={selectStyle}>
          <option value="">Select {scopeType}...</option>
          {scopeOptions.map((v: string) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : (
        <input
          value={scopeValue}
          onChange={(e) => setScopeValue(e.target.value)}
          placeholder={`${scopeType} name`}
          style={{ ...selectStyle, width: 160 }}
        />
      )}

      <select value={period} onChange={(e) => setPeriod(e.target.value as any)} style={selectStyle}>
        <option value="daily">Daily</option>
        <option value="monthly">Monthly</option>
      </select>

      <input
        type="number"
        min="0"
        step="0.01"
        value={limitUsd}
        onChange={(e) => setLimitUsd(e.target.value)}
        placeholder="$ limit"
        style={{ ...selectStyle, width: 80 }}
      />

      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        style={{
          padding: "5px 14px",
          fontSize: 12,
          fontWeight: 600,
          background: canSubmit ? t.accent : t.surfaceRaised,
          color: canSubmit ? "#fff" : t.textDim,
          border: `1px solid ${canSubmit ? t.accent : t.surfaceBorder}`,
          borderRadius: 6,
          cursor: canSubmit ? "pointer" : "default",
        }}
      >
        {createMutation.isPending ? "Adding..." : "Add"}
      </button>

      {createMutation.isError && (
        <span style={{ color: t.danger, fontSize: 12 }}>
          {(createMutation.error as any)?.message || "Failed to create"}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Limits list (matches CostTable layout from Overview)
// ---------------------------------------------------------------------------

function LimitsTable() {
  const t = useThemeTokens();
  const { data: limits, isLoading } = useUsageLimits();
  const updateMutation = useUpdateUsageLimit();
  const deleteMutation = useDeleteUsageLimit();

  if (isLoading) return <ActivityIndicator style={{ marginTop: 20 }} />;
  if (!limits || limits.length === 0) {
    return (
      <div style={{ color: t.textDim, fontSize: 12, marginTop: 8 }}>
        No limits configured.
      </div>
    );
  }

  return (
    <div style={{ border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8, overflow: "hidden" }}>
      {/* Header — matches CostTable */}
      <div
        style={{
          display: "flex",
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
            display: "flex",
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
              onClick={() => { if (confirm("Delete this limit?")) deleteMutation.mutate(lim.id); }}
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export function LimitsTab({ knownModels }: { knownModels: string[] }) {
  const t = useThemeTokens();
  const { data: statuses, isLoading } = useUsageLimitsStatus();

  return (
    <View>
      {/* Status cards */}
      {isLoading ? (
        <ActivityIndicator />
      ) : statuses && statuses.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 20 }}>
          {statuses.map((s) => (
            <LimitStatusCard key={s.id} s={s} />
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
    </View>
  );
}
