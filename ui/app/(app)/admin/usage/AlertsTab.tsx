import { useState, useRef, useCallback, useEffect } from "react";
import { View, ActivityIndicator } from "react-native";
import { BellOff, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Send } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useSpikeConfig,
  useUpdateSpikeConfig,
  useSpikeStatus,
  useSpikeAlertHistory,
  useTestSpikeAlert,
  useAvailableTargets,
} from "@/src/api/hooks/useSpikeAlerts";
import type { SpikeAlert, TargetOption, AvailableIntegration } from "@/src/types/api";

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

// ---------------------------------------------------------------------------
// Status Banner
// ---------------------------------------------------------------------------
function StatusBanner() {
  const t = useThemeTokens();
  const { data: status, isLoading: statusLoading } = useSpikeStatus();
  const { data: config } = useSpikeConfig();

  if (statusLoading || !status) {
    return (
      <View className="items-center justify-center" style={{ padding: 20 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  if (!status.enabled) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "12px 16px",
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 8,
          fontSize: 13,
          color: t.textDim,
        }}
      >
        <BellOff size={16} />
        Spike alerts are disabled. Enable them below to start monitoring.
      </div>
    );
  }

  const statusColor = status.spiking ? t.danger : t.success;
  const dotStyle: React.CSSProperties = {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: statusColor,
    flexShrink: 0,
  };
  if (status.spiking) {
    Object.assign(dotStyle, {
      boxShadow: `0 0 6px ${t.danger}`,
    });
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        background: status.spiking ? t.dangerSubtle : t.surfaceRaised,
        border: `1px solid ${status.spiking ? t.dangerBorder : t.surfaceBorder}`,
        borderRadius: 8,
      }}
    >
      <div style={dotStyle} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
          {status.spiking ? "SPIKE DETECTED" : "Normal"}
          {status.spike_ratio != null && ` (${status.spike_ratio.toFixed(1)}x baseline)`}
        </div>
        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
          Current: {fmtCost(status.window_rate)}/hr &middot; Baseline: {fmtCost(status.baseline_rate)}/hr
          {status.cooldown_active && (
            <span style={{ color: t.warning, marginLeft: 8 }}>
              Cooldown: {Math.ceil(status.cooldown_remaining_seconds / 60)}min remaining
            </span>
          )}
        </div>
      </div>
      {config?.last_check_at && (
        <div style={{ fontSize: 10, color: t.textDim, textAlign: "right" }}>
          Checked {fmtRelativeTime(config.last_check_at)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Debounced number input — saves on blur or after 800ms idle
// ---------------------------------------------------------------------------
function DebouncedNumberInput({
  value,
  onChange,
  style,
  step,
  min,
}: {
  value: number;
  onChange: (v: number) => void;
  style: React.CSSProperties;
  step?: string;
  min?: number;
}) {
  const [local, setLocal] = useState(String(value));
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Sync from parent when value changes externally
  useEffect(() => {
    setLocal(String(value));
  }, [value]);

  const flush = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const parsed = step ? parseFloat(local) : parseInt(local);
    if (!isNaN(parsed) && parsed !== value) {
      onChange(parsed);
    }
  }, [local, value, onChange, step]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLocal(e.target.value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const parsed = step ? parseFloat(e.target.value) : parseInt(e.target.value);
      if (!isNaN(parsed)) onChange(parsed);
    }, 800);
  };

  return (
    <input
      type="number"
      value={local}
      onChange={handleChange}
      onBlur={flush}
      style={style}
      step={step}
      min={min}
    />
  );
}

// ---------------------------------------------------------------------------
// Config Form
// ---------------------------------------------------------------------------
function ConfigForm() {
  const t = useThemeTokens();
  const { data: config, isLoading } = useSpikeConfig();
  const updateConfig = useUpdateSpikeConfig();
  const { data: targetsData } = useAvailableTargets();
  const testAlert = useTestSpikeAlert();
  const [addingIntegration, setAddingIntegration] = useState<AvailableIntegration | null>(null);
  const [newClientId, setNewClientId] = useState("");

  if (isLoading || !config) {
    return (
      <View className="items-center justify-center" style={{ padding: 20 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const availableOptions = targetsData?.options ?? [];
  const availableIntegrations = targetsData?.integrations ?? [];

  const inputStyle: React.CSSProperties = {
    background: t.inputBg,
    color: t.text,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 8,
    padding: "7px 12px",
    fontSize: 13,
    outline: "none",
    height: 36,
    width: 110,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 600,
    color: t.textMuted,
    marginBottom: 4,
  };

  const hintStyle: React.CSSProperties = {
    fontSize: 10,
    color: t.textDim,
    marginTop: 3,
  };

  const handleUpdate = (field: string, value: any) => {
    updateConfig.mutate({ [field]: value });
  };

  const isTargetSelected = (opt: TargetOption) => {
    return (config.targets || []).some((tgt) => {
      if (opt.type === "channel") return tgt.type === "channel" && tgt.channel_id === opt.channel_id;
      return tgt.type === "integration" && tgt.client_id === opt.client_id;
    });
  };

  const toggleTarget = (opt: TargetOption) => {
    const current = config.targets || [];
    if (isTargetSelected(opt)) {
      const filtered = current.filter((tgt) => {
        if (opt.type === "channel") return !(tgt.type === "channel" && tgt.channel_id === opt.channel_id);
        return !(tgt.type === "integration" && tgt.client_id === opt.client_id);
      });
      handleUpdate("targets", filtered);
    } else {
      const newTarget: Record<string, any> = { type: opt.type, label: opt.label };
      if (opt.type === "channel") newTarget.channel_id = opt.channel_id;
      else {
        newTarget.integration_type = opt.integration_type;
        newTarget.client_id = opt.client_id;
      }
      handleUpdate("targets", [...current, newTarget]);
    }
  };

  const removeTarget = (idx: number) => {
    const current = config.targets || [];
    handleUpdate("targets", current.filter((_, i) => i !== idx));
  };

  const addCustomTarget = () => {
    if (!addingIntegration || !newClientId.trim()) return;
    const clientId = newClientId.trim().startsWith(addingIntegration.client_id_prefix)
      ? newClientId.trim()
      : addingIntegration.client_id_prefix + newClientId.trim();
    const current = config.targets || [];
    // Don't add duplicates
    if (current.some((tgt) => tgt.type === "integration" && tgt.client_id === clientId)) {
      setAddingIntegration(null);
      setNewClientId("");
      return;
    }
    const newTarget = {
      type: "integration" as const,
      integration_type: addingIntegration.integration_type,
      client_id: clientId,
      label: clientId,
    };
    handleUpdate("targets", [...current, newTarget]);
    setAddingIntegration(null);
    setNewClientId("");
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: 16,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Configuration</div>
        {updateConfig.isPending && (
          <span style={{ fontSize: 10, color: t.textDim }}>Saving...</span>
        )}
      </div>

      {/* Enable toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <label style={{ ...labelStyle, marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => handleUpdate("enabled", e.target.checked)}
            style={{ accentColor: t.accent }}
          />
          Enable spike detection
        </label>
      </div>

      {/* Only show config details when enabled */}
      {config.enabled && (
        <>
          {/* Threshold fields */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <div>
              <div style={labelStyle}>Window (minutes)</div>
              <DebouncedNumberInput
                value={config.window_minutes}
                onChange={(v) => handleUpdate("window_minutes", Math.max(1, v))}
                style={inputStyle}
                min={1}
              />
              <div style={hintStyle}>How far back to measure current rate</div>
            </div>
            <div>
              <div style={labelStyle}>Baseline (hours)</div>
              <DebouncedNumberInput
                value={config.baseline_hours}
                onChange={(v) => handleUpdate("baseline_hours", Math.max(1, v))}
                style={inputStyle}
                min={1}
              />
              <div style={hintStyle}>History period for "normal" rate</div>
            </div>
            <div>
              <div style={labelStyle}>Relative threshold</div>
              <DebouncedNumberInput
                value={config.relative_threshold}
                onChange={(v) => handleUpdate("relative_threshold", Math.max(0, v))}
                style={inputStyle}
                step="0.1"
                min={0}
              />
              <div style={hintStyle}>Alert when rate exceeds Nx baseline</div>
            </div>
            <div>
              <div style={labelStyle}>Absolute ($/hr)</div>
              <DebouncedNumberInput
                value={config.absolute_threshold_usd}
                onChange={(v) => handleUpdate("absolute_threshold_usd", Math.max(0, v))}
                style={inputStyle}
                step="0.01"
                min={0}
              />
              <div style={hintStyle}>Alert above this rate regardless (0 = off)</div>
            </div>
            <div>
              <div style={labelStyle}>Cooldown (minutes)</div>
              <DebouncedNumberInput
                value={config.cooldown_minutes}
                onChange={(v) => handleUpdate("cooldown_minutes", Math.max(0, v))}
                style={inputStyle}
                min={0}
              />
              <div style={hintStyle}>Min time between alerts</div>
            </div>
          </div>

          {/* Target picker */}
          <div>
            <div style={labelStyle}>Alert Targets</div>

            {/* Currently configured targets */}
            {(config.targets || []).length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {(config.targets || []).map((tgt, i) => (
                  <span
                    key={i}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "4px 10px",
                      fontSize: 12,
                      background: t.accentSubtle,
                      color: t.accent,
                      border: `1px solid ${t.accent}`,
                      borderRadius: 6,
                      fontWeight: 600,
                    }}
                  >
                    {tgt.label || tgt.channel_id || tgt.client_id || "unknown"}
                    <button
                      onClick={() => removeTarget(i)}
                      style={{
                        background: "none",
                        border: "none",
                        color: t.accent,
                        cursor: "pointer",
                        padding: 0,
                        fontSize: 14,
                        lineHeight: 1,
                        marginLeft: 2,
                      }}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}

            {/* Available targets from channels/bindings */}
            {availableOptions.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                {availableOptions
                  .filter((opt) => !isTargetSelected(opt))
                  .map((opt, i) => (
                    <button
                      key={i}
                      onClick={() => toggleTarget(opt)}
                      style={{
                        padding: "5px 12px",
                        fontSize: 12,
                        background: t.surfaceOverlay,
                        color: t.textMuted,
                        border: `1px solid ${t.surfaceBorder}`,
                        borderRadius: 6,
                        cursor: "pointer",
                        fontWeight: 400,
                      }}
                    >
                      + {opt.label}
                    </button>
                  ))}
              </div>
            )}

            {/* Add custom integration target */}
            {availableIntegrations.length > 0 && !addingIntegration && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {availableIntegrations.map((integ) => (
                  <button
                    key={integ.integration_type}
                    onClick={() => {
                      setAddingIntegration(integ);
                      setNewClientId("");
                    }}
                    style={{
                      padding: "4px 10px",
                      fontSize: 11,
                      background: "none",
                      color: t.textDim,
                      border: `1px dashed ${t.surfaceBorder}`,
                      borderRadius: 6,
                      cursor: "pointer",
                    }}
                  >
                    + Add {integ.integration_type} target
                  </button>
                ))}
              </div>
            )}

            {/* Custom target input */}
            {addingIntegration && (
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
                <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 600 }}>
                  {addingIntegration.integration_type}:
                </span>
                <input
                  type="text"
                  placeholder={`${addingIntegration.client_id_prefix}...`}
                  value={newClientId}
                  onChange={(e) => setNewClientId(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") addCustomTarget();
                    if (e.key === "Escape") { setAddingIntegration(null); setNewClientId(""); }
                  }}
                  autoFocus
                  style={{
                    ...inputStyle,
                    width: 240,
                  }}
                />
                <button
                  onClick={addCustomTarget}
                  disabled={!newClientId.trim()}
                  style={{
                    padding: "6px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    background: t.accent,
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: newClientId.trim() ? "pointer" : "not-allowed",
                    opacity: newClientId.trim() ? 1 : 0.5,
                  }}
                >
                  Add
                </button>
                <button
                  onClick={() => { setAddingIntegration(null); setNewClientId(""); }}
                  style={{
                    padding: "6px 10px",
                    fontSize: 12,
                    background: "none",
                    color: t.textDim,
                    border: `1px solid ${t.surfaceBorder}`,
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
            )}

            {availableOptions.length === 0 && availableIntegrations.length === 0 && (config.targets || []).length === 0 && (
              <div style={{ fontSize: 12, color: t.textDim }}>
                No integrations with dispatch support found. Set up a Slack, Discord, or other integration first.
              </div>
            )}
          </div>

          {/* Test alert button */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              onClick={() => testAlert.mutate()}
              disabled={testAlert.isPending || (config.targets || []).length === 0}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "7px 14px",
                fontSize: 12,
                fontWeight: 600,
                background: t.warningSubtle,
                color: t.warning,
                border: `1px solid ${t.warningBorder}`,
                borderRadius: 6,
                cursor: testAlert.isPending || (config.targets || []).length === 0 ? "not-allowed" : "pointer",
                opacity: testAlert.isPending || (config.targets || []).length === 0 ? 0.5 : 1,
              }}
            >
              <Send size={12} />
              {testAlert.isPending ? "Sending..." : "Send Test Alert"}
            </button>
            {(config.targets || []).length === 0 && (
              <span style={{ fontSize: 11, color: t.textDim }}>Select at least one target first</span>
            )}
            {testAlert.data && (
              <span style={{ fontSize: 11, color: testAlert.data.ok ? t.success : t.danger }}>
                {testAlert.data.ok
                  ? `Sent! ${testAlert.data.targets_succeeded}/${testAlert.data.targets_attempted} targets`
                  : "Failed"}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Alert History
// ---------------------------------------------------------------------------
function AlertHistory() {
  const t = useThemeTokens();
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading } = useSpikeAlertHistory(page);

  if (isLoading) {
    return (
      <View className="items-center justify-center" style={{ padding: 20 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  if (!data || data.alerts.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: "center", color: t.textDim, fontSize: 13 }}>
        No spike alerts have been fired yet.
      </div>
    );
  }

  const totalPages = Math.ceil(data.total / data.page_size);

  return (
    <div
      style={{
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, padding: "12px 16px", borderBottom: `1px solid ${t.surfaceBorder}` }}>
        Alert History ({data.total} total)
      </div>

      {/* Header */}
      <div
        style={{
          display: "flex",
          gap: 8,
          padding: "8px 16px",
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          textTransform: "uppercase",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          background: t.surfaceOverlay,
        }}
      >
        <span style={{ width: 140 }}>Time</span>
        <span style={{ width: 90, textAlign: "right" }}>Rate</span>
        <span style={{ width: 90, textAlign: "right" }}>Baseline</span>
        <span style={{ width: 60, textAlign: "right" }}>Ratio</span>
        <span style={{ width: 80 }}>Trigger</span>
        <span style={{ flex: 1, textAlign: "right" }}>Delivery</span>
        <span style={{ width: 20 }} />
      </div>

      {data.alerts.map((alert: SpikeAlert) => (
        <div key={alert.id}>
          <div
            onClick={() => setExpanded(expanded === alert.id ? null : alert.id)}
            style={{
              display: "flex",
              gap: 8,
              padding: "8px 16px",
              fontSize: 12,
              borderBottom: `1px solid ${t.surfaceRaised}`,
              alignItems: "center",
              cursor: "pointer",
            }}
            onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = t.surfaceOverlay)}
            onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "")}
          >
            <span style={{ width: 140, color: t.textMuted, fontSize: 11 }}>
              {fmtTime(alert.created_at)}
            </span>
            <span style={{ width: 90, textAlign: "right", fontFamily: "monospace", color: t.danger }}>
              {fmtCost(alert.window_rate_usd_per_hour)}/hr
            </span>
            <span style={{ width: 90, textAlign: "right", fontFamily: "monospace", color: t.textMuted }}>
              {fmtCost(alert.baseline_rate_usd_per_hour)}/hr
            </span>
            <span style={{ width: 60, textAlign: "right", fontFamily: "monospace", fontWeight: 600, color: t.text }}>
              {alert.spike_ratio != null ? `${alert.spike_ratio.toFixed(1)}x` : "--"}
            </span>
            <span style={{ width: 80, color: t.textMuted }}>
              {alert.trigger_reason}
            </span>
            <span style={{ flex: 1, textAlign: "right", color: alert.targets_succeeded === alert.targets_attempted ? t.success : t.warning }}>
              {alert.targets_succeeded}/{alert.targets_attempted}
            </span>
            <span style={{ width: 20, color: t.textDim }}>
              {expanded === alert.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </div>

          {/* Expanded detail */}
          {expanded === alert.id && (
            <div style={{ padding: "10px 16px 10px 28px", background: t.surfaceOverlay, borderBottom: `1px solid ${t.surfaceBorder}` }}>
              {alert.top_models.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Top Models</div>
                  {alert.top_models.map((m, i) => (
                    <div key={i} style={{ fontSize: 11, color: t.textMuted }}>
                      {m.model} &mdash; {fmtCost(m.cost)} ({m.calls} calls)
                    </div>
                  ))}
                </div>
              )}
              {alert.top_bots.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Top Bots</div>
                  {alert.top_bots.map((b, i) => (
                    <div key={i} style={{ fontSize: 11, color: t.textMuted }}>
                      {b.bot_id} &mdash; {fmtCost(b.cost)}
                    </div>
                  ))}
                </div>
              )}
              {alert.recent_traces.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Recent Traces</div>
                  {alert.recent_traces.map((tr, i) => (
                    <div key={i} style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
                      {tr.correlation_id.slice(0, 8)} &mdash; {tr.model} via {tr.bot_id}: {fmtCost(tr.cost)}
                    </div>
                  ))}
                </div>
              )}
              {alert.delivery_details.length > 0 && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Delivery</div>
                  {alert.delivery_details.map((d, i) => (
                    <div key={i} style={{ fontSize: 11, color: d.success ? t.success : t.danger }}>
                      {d.target?.label || d.target?.channel_id || d.target?.client_id || "unknown"}: {d.success ? "OK" : d.error || "failed"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ))}

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 12,
            padding: "10px 16px",
            borderTop: `1px solid ${t.surfaceOverlay}`,
          }}
        >
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={{
              background: "none",
              border: "none",
              cursor: page <= 1 ? "default" : "pointer",
              color: page <= 1 ? t.surfaceBorder : t.textMuted,
              padding: 4,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 12, color: t.textDim }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={{
              background: "none",
              border: "none",
              cursor: page >= totalPages ? "default" : "pointer",
              color: page >= totalPages ? t.surfaceBorder : t.textMuted,
              padding: 4,
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------
export function AlertsTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <StatusBanner />
      <ConfigForm />
      <AlertHistory />
    </div>
  );
}
