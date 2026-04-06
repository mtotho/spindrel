import { ActivityIndicator } from "react-native";
import { Shield, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSecurityAudit, type SecurityCheck } from "@/src/api/hooks/useSecurityAudit";

function scoreColor(score: number, t: ReturnType<typeof useThemeTokens>) {
  if (score >= 80) return t.success;
  if (score >= 50) return t.warning;
  return t.danger;
}

function severityColor(severity: string, t: ReturnType<typeof useThemeTokens>) {
  if (severity === "critical") return t.danger;
  if (severity === "warning") return t.warning;
  return t.textDim;
}

function statusBadge(status: string, t: ReturnType<typeof useThemeTokens>) {
  if (status === "pass") return { bg: t.successSubtle, color: t.success, label: "PASS" };
  if (status === "fail") return { bg: t.dangerSubtle, color: t.danger, label: "FAIL" };
  return { bg: t.warningSubtle, color: t.warning, label: "WARN" };
}

function CheckRow({ check }: { check: SecurityCheck }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const badge = statusBadge(check.status, t);
  const hasDetails = check.recommendation || check.details;

  const borderColor = check.status === "fail"
    ? (check.severity === "critical" ? t.dangerBorder : t.warningBorder)
    : check.status === "warning"
      ? t.warningBorder
      : t.surfaceRaised;

  return (
    <div
      style={{
        padding: "10px 14px",
        background: t.inputBg,
        borderRadius: 6,
        border: `1px solid ${borderColor}`,
        cursor: hasDetails ? "pointer" : "default",
      }}
      onClick={() => hasDetails && setExpanded(!expanded)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {/* Status badge */}
        <span style={{
          padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 700,
          background: badge.bg, color: badge.color, letterSpacing: 0.5,
          flexShrink: 0,
        }}>
          {badge.label}
        </span>
        {/* Severity dot */}
        <span style={{
          width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
          background: severityColor(check.severity, t),
        }} />
        {/* Message */}
        <span style={{ fontSize: 12, color: t.text, flex: 1 }}>{check.message}</span>
        {/* Category */}
        <span style={{
          fontSize: 10, color: t.textDim, fontFamily: "monospace", flexShrink: 0,
        }}>
          {check.category}
        </span>
        {/* Expand indicator */}
        {hasDetails && (
          expanded
            ? <ChevronDown size={12} color={t.textDim} />
            : <ChevronRight size={12} color={t.textDim} />
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: 8, paddingLeft: 22 }}>
          {check.recommendation && (
            <div style={{ fontSize: 11, color: t.accent, marginBottom: 4 }}>
              {check.recommendation}
            </div>
          )}
          {check.details && (
            <pre style={{
              fontSize: 10, color: t.textMuted, fontFamily: "monospace",
              margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>
              {JSON.stringify(check.details, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function SecurityAuditSection() {
  const t = useThemeTokens();
  const { data, isLoading, error } = useSecurityAudit();

  if (isLoading) {
    return (
      <div style={{ padding: 16, display: "flex", justifyContent: "center" }}>
        <ActivityIndicator color={t.accent} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: 16, fontSize: 12, color: t.danger }}>
        Failed to load security audit{error ? `: ${error.message}` : ""}
      </div>
    );
  }

  const criticalFails = data.checks.filter(c => c.severity === "critical" && c.status === "fail");
  const warningFails = data.checks.filter(c => c.severity === "warning" && c.status === "fail");
  const notices = data.checks.filter(c => c.severity === "info" && c.status === "warning");
  const passed = data.checks.filter(c => c.status === "pass");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Score banner */}
      <div style={{
        padding: "16px 20px",
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
        display: "flex", alignItems: "center", gap: 16,
      }}>
        <Shield size={24} color={scoreColor(data.score, t)} />
        <div>
          <div style={{ fontSize: 28, fontWeight: 800, fontFamily: "monospace", color: scoreColor(data.score, t) }}>
            {data.score}
          </div>
          <div style={{ fontSize: 11, color: t.textDim }}>Security Score</div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 12, fontSize: 11, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {(data.summary.fail ?? 0) > 0 && (
            <span style={{ color: t.danger, fontWeight: 600 }}>
              {data.summary.fail} failed
            </span>
          )}
          {(data.summary.warn ?? 0) > 0 && (
            <span style={{ color: t.warning, fontWeight: 600 }}>
              {data.summary.warn} notice{data.summary.warn !== 1 ? "s" : ""}
            </span>
          )}
          <span style={{ color: t.success }}>
            {data.summary.pass ?? 0} passed
          </span>
          <span style={{ color: t.textDim }}>
            {data.checks.length} total
          </span>
        </div>
      </div>

      {/* Critical failures */}
      {criticalFails.length > 0 && (
        <div>
          <div style={{
            fontSize: 11, fontWeight: 600, color: t.danger,
            marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5,
          }}>
            Critical ({criticalFails.length})
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {criticalFails.map(c => <CheckRow key={c.id} check={c} />)}
          </div>
        </div>
      )}

      {/* Warning failures */}
      {warningFails.length > 0 && (
        <div>
          <div style={{
            fontSize: 11, fontWeight: 600, color: t.warning,
            marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5,
          }}>
            Warnings ({warningFails.length})
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {warningFails.map(c => <CheckRow key={c.id} check={c} />)}
          </div>
        </div>
      )}

      {/* Info notices (info-severity checks that flagged something) */}
      {notices.length > 0 && (
        <div>
          <div style={{
            fontSize: 11, fontWeight: 600, color: t.warningMuted,
            marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5,
          }}>
            Notices ({notices.length})
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {notices.map(c => <CheckRow key={c.id} check={c} />)}
          </div>
        </div>
      )}

      {/* Passed checks — collapsed by default */}
      {passed.length > 0 && <PassedSection checks={passed} />}
    </div>
  );
}

function PassedSection({ checks }: { checks: SecurityCheck[] }) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);

  return (
    <div>
      <div
        onClick={() => setOpen(!open)}
        style={{
          fontSize: 11, fontWeight: 600, color: t.success,
          marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5,
          cursor: "pointer", display: "flex", alignItems: "center", gap: 4,
          userSelect: "none",
        }}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Passed ({checks.length})
      </div>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {checks.map(c => <CheckRow key={c.id} check={c} />)}
        </div>
      )}
    </div>
  );
}
