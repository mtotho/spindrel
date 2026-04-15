import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useStorageBreakdown, usePurgeStorage } from "@/src/api/hooks/useStorage";
import { useThemeTokens } from "@/src/theme/tokens";
import { BarChart } from "@/src/components/shared/SimpleCharts";
import { Trash2, Settings, Info } from "lucide-react";

const TABLE_LABELS: Record<string, string> = {
  trace_events: "Trace Events",
  tool_calls: "Tool Calls",
  model_fallback_events: "Model Fallbacks",
  tool_approvals: "Tool Approvals",
  compaction_logs: "Compaction Logs",
  heartbeat_runs: "Heartbeat Runs",
  workflow_runs: "Workflow Runs",
  tasks: "Tasks",
};

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function fmtBytes(b: number): string {
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`;
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

export function StorageSection() {
  const t = useThemeTokens();
  const { data, isLoading } = useStorageBreakdown();
  const purge = usePurgeStorage();
  const [showConfirm, setShowConfirm] = useState(false);

  if (isLoading) {
    return (
      <div className="items-center justify-center" style={{ padding: 40 }}>
        <Spinner color={t.accent} />
      </div>
    );
  }

  if (!data) return null;

  const totalRows = data.tables.reduce((sum, tb) => sum + tb.row_count, 0);
  const totalPurgeable = data.tables.reduce((sum, tb) => sum + tb.purgeable, 0);
  const totalSize = data.tables.reduce((sum, tb) => sum + (tb.size_bytes ?? 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Retention disabled nudge */}
      {data.retention_days == null && totalRows > 0 && (
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 10,
            padding: "12px 16px",
            background: t.accentSubtle,
            border: `1px solid ${t.accentBorder}`,
            borderRadius: 8,
            fontSize: 13,
            color: t.textMuted,
          }}
        >
          <Info size={16} style={{ flexShrink: 0, color: t.accent }} />
          <span>
            Data retention is <strong style={{ color: t.text }}>off</strong> — operational data is kept indefinitely.
          </span>
          <a
            href="/admin/settings#Data%20Retention"
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 4,
              marginLeft: "auto",
              color: t.accent,
              fontSize: 12,
              fontWeight: 600,
              textDecoration: "none",
              flexShrink: 0,
            }}
          >
            <Settings size={12} /> Configure
          </a>
        </div>
      )}

      {/* Summary cards */}
      <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
        <SummaryCard label="Total Rows" value={fmtNum(totalRows)} t={t} />
        <SummaryCard
          label="Disk Usage"
          value={totalSize > 0 ? fmtBytes(totalSize) : "N/A"}
          t={t}
        />
        <SummaryCard
          label="Retention"
          value={data.retention_days != null ? `${data.retention_days}d` : "Off"}
          sub={data.retention_days != null ? `Sweep every ${Math.round(data.sweep_interval_s / 3600)}h` : "Keeping all data"}
          t={t}
        />
        {data.retention_days != null && (
          <SummaryCard
            label="Purgeable"
            value={fmtNum(totalPurgeable)}
            sub={totalPurgeable > 0 ? "rows eligible for deletion" : "nothing to purge"}
            t={t}
          />
        )}
      </div>

      {/* Size bar chart */}
      {totalSize > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
            Disk Usage by Table
          </div>
          <BarChart
            items={data.tables
              .filter((tb) => tb.size_bytes != null && tb.size_bytes > 0)
              .map((tb) => ({
                label: TABLE_LABELS[tb.table] ?? tb.table,
                value: tb.size_bytes!,
              }))}
            formatValue={fmtBytes}
          />
        </div>
      )}

      {/* Table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
          Table Details
        </div>
        <div style={{ border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8, overflow: "hidden" }}>
          {/* Header */}
          <div
            style={{
              display: "flex", flexDirection: "row",
              gap: 8,
              padding: "8px 12px",
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              borderBottom: `1px solid ${t.surfaceOverlay}`,
              background: t.surfaceOverlay,
            }}
          >
            <span style={{ flex: 1, minWidth: 0 }}>Table</span>
            <span style={{ width: 80, textAlign: "right" }}>Rows</span>
            <span style={{ width: 80, textAlign: "right" }}>Size</span>
            <span style={{ width: 100, textAlign: "right" }}>Oldest</span>
            {data.retention_days != null && (
              <span style={{ width: 80, textAlign: "right" }}>Purgeable</span>
            )}
          </div>
          {data.tables.map((tb, i) => (
            <div
              key={tb.table}
              style={{
                display: "flex", flexDirection: "row",
                gap: 8,
                padding: "7px 12px",
                fontSize: 12,
                borderBottom: i < data.tables.length - 1 ? `1px solid ${t.surfaceRaised}` : "none",
                alignItems: "center",
              }}
            >
              <span style={{ flex: 1, minWidth: 0, color: t.text }}>
                {TABLE_LABELS[tb.table] ?? tb.table}
              </span>
              <span style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
                {fmtNum(tb.row_count)}
              </span>
              <span style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
                {tb.size_display ?? "--"}
              </span>
              <span style={{ width: 100, textAlign: "right", color: t.textDim, fontSize: 11 }}>
                {fmtDate(tb.oldest_row)}
              </span>
              {data.retention_days != null && (
                <span
                  style={{
                    width: 80,
                    textAlign: "right",
                    fontFamily: "monospace",
                    color: tb.purgeable > 0 ? t.warning : t.textDim,
                    fontWeight: tb.purgeable > 0 ? 600 : 400,
                  }}
                >
                  {fmtNum(tb.purgeable)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Purge button */}
      {data.retention_days != null && totalPurgeable > 0 && (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
          {!showConfirm ? (
            <button
              onClick={() => {
                purge.reset();
                setShowConfirm(true);
              }}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                fontSize: 13,
                fontWeight: 600,
                background: t.danger,
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              <Trash2 size={14} />
              Purge {fmtNum(totalPurgeable)} rows now
            </button>
          ) : (
            <>
              <span style={{ fontSize: 13, color: t.warning, fontWeight: 600 }}>
                Delete {fmtNum(totalPurgeable)} rows older than {data.retention_days} days?
              </span>
              <button
                onClick={() => {
                  purge.mutate();
                  setShowConfirm(false);
                }}
                disabled={purge.isPending}
                style={{
                  padding: "6px 14px",
                  fontSize: 12,
                  fontWeight: 600,
                  background: t.danger,
                  color: "#fff",
                  border: "none",
                  borderRadius: 4,
                  cursor: "pointer",
                  opacity: purge.isPending ? 0.6 : 1,
                }}
              >
                {purge.isPending ? "Purging..." : "Confirm"}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                style={{
                  padding: "6px 14px",
                  fontSize: 12,
                  background: "transparent",
                  color: t.textMuted,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      )}

      {/* Purge result feedback (shown below, outside the conditional purge button area) */}
      {purge.isSuccess && !showConfirm && (
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            background: t.successBorder,
            borderRadius: 6,
            fontSize: 12,
            color: t.success,
            fontWeight: 600,
          }}
        >
          Purged {purge.data.total} rows successfully
        </div>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  sub,
  t,
}: {
  label: string;
  value: string;
  sub?: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 140,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: "14px 16px",
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div style={{ fontSize: 11, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}
