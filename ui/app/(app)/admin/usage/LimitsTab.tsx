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
} from "@/src/api/hooks/useUsageLimits";
import { useThemeTokens } from "@/src/theme/tokens";

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function progressColor(pct: number): string {
  if (pct >= 90) return "#ef4444";
  if (pct >= 70) return "#f59e0b";
  return "#22c55e";
}

// ---------------------------------------------------------------------------
// Status cards
// ---------------------------------------------------------------------------

function LimitStatusCard({ s }: { s: UsageLimitStatus }) {
  const t = useThemeTokens();
  const color = progressColor(s.percentage);
  return (
    <div
      style={{
        flex: 1,
        minWidth: 220,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: "14px 16px",
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 4,
        }}
      >
        {s.scope_type}: {s.scope_value}
      </div>
      <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8 }}>
        {s.period}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: t.text,
          fontFamily: "monospace",
          marginBottom: 8,
        }}
      >
        {fmtCost(s.current_spend)} / {fmtCost(s.limit_usd)}{" "}
        <span style={{ fontSize: 13, fontWeight: 400, color: t.textMuted }}>
          ({s.percentage}%)
        </span>
      </div>
      {/* Progress bar */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: t.surfaceOverlay,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${Math.min(s.percentage, 100)}%`,
            background: color,
            borderRadius: 3,
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
  const { data: bots } = useBots();
  const createMutation = useCreateUsageLimit();

  const [scopeType, setScopeType] = useState<"model" | "bot">("model");
  const [scopeValue, setScopeValue] = useState("");
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [limitUsd, setLimitUsd] = useState("");

  const selectStyle: React.CSSProperties = {
    background: t.surfaceRaised,
    color: t.textMuted,
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 6,
    padding: "5px 10px",
    fontSize: 12,
    outline: "none",
  };

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

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center",
        marginTop: 16,
        padding: "12px 16px",
        background: t.surfaceRaised,
        borderRadius: 8,
        border: `1px solid ${t.surfaceOverlay}`,
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
          style={{ ...selectStyle, width: 180 }}
        />
      )}

      <select value={period} onChange={(e) => setPeriod(e.target.value as any)} style={selectStyle}>
        <option value="daily">Daily</option>
        <option value="monthly">Monthly</option>
      </select>

      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{ color: t.textMuted, fontSize: 13 }}>$</span>
        <input
          type="number"
          min="0"
          step="0.01"
          value={limitUsd}
          onChange={(e) => setLimitUsd(e.target.value)}
          placeholder="5.00"
          style={{ ...selectStyle, width: 80 }}
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={createMutation.isPending || !scopeValue || !limitUsd}
        style={{
          background: t.accent,
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: "6px 14px",
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
          opacity: createMutation.isPending || !scopeValue || !limitUsd ? 0.5 : 1,
        }}
      >
        {createMutation.isPending ? "Adding..." : "Add Limit"}
      </button>

      {createMutation.isError && (
        <span style={{ color: "#ef4444", fontSize: 12 }}>
          {(createMutation.error as any)?.message || "Failed to create"}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// All limits table
// ---------------------------------------------------------------------------

function LimitsTable() {
  const t = useThemeTokens();
  const { data: limits, isLoading } = useUsageLimits();
  const updateMutation = useUpdateUsageLimit();
  const deleteMutation = useDeleteUsageLimit();

  if (isLoading) return <ActivityIndicator style={{ marginTop: 20 }} />;
  if (!limits || limits.length === 0) {
    return (
      <div style={{ color: t.textDim, fontSize: 13, marginTop: 16 }}>
        No limits configured yet.
      </div>
    );
  }

  const cellStyle: React.CSSProperties = {
    padding: "8px 12px",
    fontSize: 12,
    borderBottom: `1px solid ${t.surfaceOverlay}`,
  };

  return (
    <div
      style={{
        marginTop: 16,
        border: `1px solid ${t.surfaceOverlay}`,
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: t.surfaceOverlay }}>
            <th style={{ ...cellStyle, textAlign: "left", color: t.textDim, fontWeight: 500 }}>Scope</th>
            <th style={{ ...cellStyle, textAlign: "left", color: t.textDim, fontWeight: 500 }}>Value</th>
            <th style={{ ...cellStyle, textAlign: "left", color: t.textDim, fontWeight: 500 }}>Period</th>
            <th style={{ ...cellStyle, textAlign: "right", color: t.textDim, fontWeight: 500 }}>Limit</th>
            <th style={{ ...cellStyle, textAlign: "center", color: t.textDim, fontWeight: 500 }}>Enabled</th>
            <th style={{ ...cellStyle, textAlign: "center", color: t.textDim, fontWeight: 500 }}></th>
          </tr>
        </thead>
        <tbody>
          {limits.map((lim) => (
            <tr key={lim.id}>
              <td style={{ ...cellStyle, color: t.text }}>{lim.scope_type}</td>
              <td style={{ ...cellStyle, color: t.text, fontFamily: "monospace" }}>{lim.scope_value}</td>
              <td style={{ ...cellStyle, color: t.text }}>{lim.period}</td>
              <td style={{ ...cellStyle, color: t.text, textAlign: "right", fontFamily: "monospace" }}>
                ${lim.limit_usd.toFixed(2)}
              </td>
              <td style={{ ...cellStyle, textAlign: "center" }}>
                <input
                  type="checkbox"
                  checked={lim.enabled}
                  onChange={() =>
                    updateMutation.mutate({ id: lim.id, enabled: !lim.enabled })
                  }
                />
              </td>
              <td style={{ ...cellStyle, textAlign: "center" }}>
                <button
                  onClick={() => { if (confirm("Delete this limit?")) deleteMutation.mutate(lim.id); }}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: t.textDim,
                    padding: 4,
                  }}
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main exported tab
// ---------------------------------------------------------------------------

export function LimitsTab({ knownModels }: { knownModels: string[] }) {
  const t = useThemeTokens();
  const { data: statuses, isLoading } = useUsageLimitsStatus();

  return (
    <View>
      {/* Status cards */}
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
        Active Limits
      </div>
      {isLoading ? (
        <ActivityIndicator />
      ) : statuses && statuses.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {statuses.map((s) => (
            <LimitStatusCard key={s.id} s={s} />
          ))}
        </div>
      ) : (
        <div style={{ color: t.textDim, fontSize: 13 }}>No active limits.</div>
      )}

      {/* Add form */}
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginTop: 24, marginBottom: 4 }}>
        Add Limit
      </div>
      <AddLimitForm knownModels={knownModels} />

      {/* All limits */}
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginTop: 24, marginBottom: 4 }}>
        All Limits
      </div>
      <LimitsTable />
    </View>
  );
}
