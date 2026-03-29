import { useState } from "react";
import { View, ActivityIndicator } from "react-native";
import { Plus, Trash2, ShieldCheck } from "lucide-react";
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
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function progressColor(pct: number): string {
  if (pct >= 90) return "#ef4444";
  if (pct >= 70) return "#eab308";
  return "#22c55e";
}

function progressTrack(t: ThemeTokens): string {
  return t.surfaceBorder;
}

function scopeLabel(s: { scope_type: string; scope_value: string }): string {
  return s.scope_value;
}

function periodLabel(p: string): string {
  return p === "daily" ? "Daily" : "Monthly";
}

// Shared input/select styling using proper input tokens
function inputStyle(t: ThemeTokens): React.CSSProperties {
  return {
    background: t.inputBg,
    color: t.inputText,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 6,
    padding: "7px 10px",
    fontSize: 13,
    outline: "none",
    lineHeight: "1.4",
  };
}

// ---------------------------------------------------------------------------
// Toggle switch (replaces raw checkbox)
// ---------------------------------------------------------------------------

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  const t = useThemeTokens();
  return (
    <button
      onClick={onChange}
      disabled={disabled}
      style={{
        position: "relative",
        width: 34,
        height: 18,
        borderRadius: 9,
        border: "none",
        background: checked ? t.accent : t.surfaceBorder,
        cursor: disabled ? "default" : "pointer",
        padding: 0,
        transition: "background 0.2s",
        opacity: disabled ? 0.5 : 1,
        flexShrink: 0,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 18 : 2,
          width: 14,
          height: 14,
          borderRadius: 7,
          background: "#fff",
          transition: "left 0.2s",
          boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
        }}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Status cards
// ---------------------------------------------------------------------------

function LimitStatusCard({ s }: { s: UsageLimitStatus }) {
  const t = useThemeTokens();
  const color = progressColor(s.percentage);
  const badge = s.scope_type === "model" ? "Model" : "Bot";

  return (
    <div
      style={{
        flex: "1 1 260px",
        maxWidth: 360,
        background: t.surfaceRaised,
        borderRadius: 10,
        padding: "16px 18px",
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      {/* Header row: scope badge + period */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: t.accent,
              background: t.accentMuted,
              padding: "2px 6px",
              borderRadius: 4,
            }}
          >
            {badge}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
            {scopeLabel(s)}
          </span>
        </div>
        <span
          style={{
            fontSize: 11,
            color: t.textMuted,
            fontWeight: 500,
          }}
        >
          {periodLabel(s.period)}
        </span>
      </div>

      {/* Spend numbers */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 10 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>
          {fmtCost(s.current_spend)}
        </span>
        <span style={{ fontSize: 13, color: t.textMuted }}>
          / {fmtCost(s.limit_usd)}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color,
            marginLeft: "auto",
          }}
        >
          {s.percentage}%
        </span>
      </div>

      {/* Progress bar */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: progressTrack(t),
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

  const iStyle = inputStyle(t);

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
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
        gap: 12,
        padding: "16px 18px",
        background: t.surfaceRaised,
        borderRadius: 10,
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      {/* Scope type */}
      <div>
        <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: t.textMuted, marginBottom: 4 }}>
          Scope
        </label>
        <select
          value={scopeType}
          onChange={(e) => { setScopeType(e.target.value as any); setScopeValue(""); }}
          style={{ ...iStyle, width: "100%" }}
        >
          <option value="model">Model</option>
          <option value="bot">Bot</option>
        </select>
      </div>

      {/* Scope value */}
      <div style={{ gridColumn: "span 1" }}>
        <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: t.textMuted, marginBottom: 4 }}>
          {scopeType === "model" ? "Model" : "Bot"}
        </label>
        {scopeOptions.length > 0 ? (
          <select value={scopeValue} onChange={(e) => setScopeValue(e.target.value)} style={{ ...iStyle, width: "100%" }}>
            <option value="">Select...</option>
            {scopeOptions.map((v: string) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input
            value={scopeValue}
            onChange={(e) => setScopeValue(e.target.value)}
            placeholder={`Enter ${scopeType}...`}
            style={{ ...iStyle, width: "100%", boxSizing: "border-box" }}
          />
        )}
      </div>

      {/* Period */}
      <div>
        <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: t.textMuted, marginBottom: 4 }}>
          Period
        </label>
        <select value={period} onChange={(e) => setPeriod(e.target.value as any)} style={{ ...iStyle, width: "100%" }}>
          <option value="daily">Daily</option>
          <option value="monthly">Monthly</option>
        </select>
      </div>

      {/* Limit amount */}
      <div>
        <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: t.textMuted, marginBottom: 4 }}>
          Limit (USD)
        </label>
        <div style={{ position: "relative" }}>
          <span
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: t.textMuted,
              fontSize: 13,
              pointerEvents: "none",
            }}
          >
            $
          </span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={limitUsd}
            onChange={(e) => setLimitUsd(e.target.value)}
            placeholder="5.00"
            style={{ ...iStyle, width: "100%", boxSizing: "border-box", paddingLeft: 22 }}
          />
        </div>
      </div>

      {/* Submit */}
      <div style={{ display: "flex", alignItems: "flex-end" }}>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: canSubmit ? t.accent : t.surfaceBorder,
            color: canSubmit ? "#fff" : t.textDim,
            border: "none",
            borderRadius: 6,
            padding: "8px 16px",
            fontSize: 13,
            fontWeight: 600,
            cursor: canSubmit ? "pointer" : "default",
            transition: "background 0.15s",
            width: "100%",
            justifyContent: "center",
          }}
        >
          <Plus size={14} />
          {createMutation.isPending ? "Adding..." : "Add Limit"}
        </button>
      </div>

      {createMutation.isError && (
        <div style={{ gridColumn: "1 / -1", color: "#ef4444", fontSize: 12, marginTop: -4 }}>
          {(createMutation.error as any)?.message || "Failed to create limit"}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Limits table
// ---------------------------------------------------------------------------

function LimitRow({ lim }: { lim: UsageLimit }) {
  const t = useThemeTokens();
  const updateMutation = useUpdateUsageLimit();
  const deleteMutation = useDeleteUsageLimit();

  const cellStyle: React.CSSProperties = {
    padding: "10px 14px",
    fontSize: 13,
    borderBottom: `1px solid ${t.surfaceBorder}`,
    verticalAlign: "middle",
  };

  const badge = lim.scope_type === "model" ? "Model" : "Bot";

  return (
    <tr style={{ opacity: lim.enabled ? 1 : 0.5, transition: "opacity 0.2s" }}>
      <td style={cellStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: t.accent,
              background: t.accentMuted,
              padding: "1px 5px",
              borderRadius: 3,
            }}
          >
            {badge}
          </span>
          <span style={{ color: t.text, fontFamily: "monospace", fontSize: 12 }}>{lim.scope_value}</span>
        </div>
      </td>
      <td style={{ ...cellStyle, color: t.text }}>{periodLabel(lim.period)}</td>
      <td style={{ ...cellStyle, color: t.text, textAlign: "right", fontFamily: "monospace" }}>
        ${lim.limit_usd.toFixed(2)}
      </td>
      <td style={{ ...cellStyle, textAlign: "center" }}>
        <Toggle
          checked={lim.enabled}
          onChange={() => updateMutation.mutate({ id: lim.id, enabled: !lim.enabled })}
          disabled={updateMutation.isPending}
        />
      </td>
      <td style={{ ...cellStyle, textAlign: "center", width: 40 }}>
        <button
          onClick={() => { if (confirm("Delete this limit?")) deleteMutation.mutate(lim.id); }}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: t.textDim,
            padding: 4,
            borderRadius: 4,
            display: "inline-flex",
            alignItems: "center",
          }}
          title="Delete"
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}

function LimitsTable() {
  const t = useThemeTokens();
  const { data: limits, isLoading } = useUsageLimits();

  if (isLoading) return <ActivityIndicator style={{ marginTop: 20 }} />;
  if (!limits || limits.length === 0) return null;

  const thStyle: React.CSSProperties = {
    padding: "8px 14px",
    fontSize: 11,
    fontWeight: 500,
    color: t.textMuted,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    borderBottom: `1px solid ${t.surfaceBorder}`,
  };

  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 10,
        overflow: "hidden",
        background: t.surfaceRaised,
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: "left" }}>Target</th>
            <th style={{ ...thStyle, textAlign: "left" }}>Period</th>
            <th style={{ ...thStyle, textAlign: "right" }}>Limit</th>
            <th style={{ ...thStyle, textAlign: "center" }}>Active</th>
            <th style={{ ...thStyle, textAlign: "center", width: 40 }}></th>
          </tr>
        </thead>
        <tbody>
          {limits.map((lim) => (
            <LimitRow key={lim.id} lim={lim} />
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
  const hasStatuses = statuses && statuses.length > 0;

  return (
    <View style={{ gap: 28 }}>
      {/* Status cards */}
      {isLoading ? (
        <ActivityIndicator />
      ) : hasStatuses ? (
        <div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: t.text,
              marginBottom: 10,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <ShieldCheck size={14} color={t.textMuted} />
            Current Usage
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {statuses!.map((s) => (
              <LimitStatusCard key={s.id} s={s} />
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: "24px 0",
            textAlign: "center",
            color: t.textDim,
            fontSize: 13,
          }}
        >
          No active limits. Add one below to start tracking spend.
        </div>
      )}

      {/* Add form */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <Plus size={14} color={t.textMuted} />
          New Limit
        </div>
        <AddLimitForm knownModels={knownModels} />
      </div>

      {/* All limits table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
          All Limits
        </div>
        <LimitsTable />
      </div>
    </View>
  );
}
