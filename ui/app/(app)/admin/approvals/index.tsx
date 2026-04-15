import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  ThumbsDown,
  ShieldCheck,
  Globe,
  Play,
} from "lucide-react";
import {
  useApprovals,
  useDecideApproval,
  useApprovalSuggestions,
  type ToolApproval,
  type RuleSuggestion,
} from "@/src/api/hooks/useApprovals";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { TabBar } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

const STATUS_TABS = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "denied", label: "Denied" },
  { key: "expired", label: "Expired" },
];

function StatusIcon({ status }: { status: string }) {
  const t = useThemeTokens();
  switch (status) {
    case "pending":
      return <Clock size={14} color={t.warningMuted} />;
    case "approved":
      return <CheckCircle size={14} color={t.success} />;
    case "denied":
      return <XCircle size={14} color={t.danger} />;
    case "expired":
      return <AlertTriangle size={14} color={t.textDim} />;
    default:
      return <Clock size={14} color={t.textDim} />;
  }
}

function StatusBadge({ status }: { status: string }) {
  const t = useThemeTokens();
  const config: Record<string, { bg: string; color: string }> = {
    pending: { bg: t.warningSubtle, color: t.warning },
    approved: { bg: t.successSubtle, color: t.success },
    denied: { bg: t.dangerSubtle, color: t.danger },
    expired: { bg: t.overlayLight, color: t.textDim },
  };
  const c = config[status] || config.expired;
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.color,
      }}
    >
      {status}
    </span>
  );
}

function SuggestionButton({
  suggestion,
  onClick,
  disabled,
}: {
  suggestion: RuleSuggestion;
  onClick: () => void;
  disabled: boolean;
}) {
  const t = useThemeTokens();
  const isGlobal = suggestion.scope === "global";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={suggestion.description}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 6,
        padding: "6px 12px",
        borderRadius: 6,
        background: isGlobal ? t.purpleSubtle : t.accentSubtle,
        border: `1px solid ${isGlobal ? t.purpleBorder : t.accentBorder}`,
        cursor: disabled ? "default" : "pointer",
        fontSize: 12,
        fontWeight: 500,
        color: isGlobal ? t.purple : t.accent,
        opacity: disabled ? 0.5 : 1,
        whiteSpace: "nowrap",
      }}
    >
      {isGlobal ? <Globe size={12} /> : <ShieldCheck size={12} />} {suggestion.label}
    </button>
  );
}

function ApprovalCard({
  approval,
  onDecide,
  onDecideWithRule,
  deciding,
}: {
  approval: ToolApproval;
  onDecide: (id: string, approved: boolean) => void;
  onDecideWithRule: (
    id: string,
    rule: { tool_name: string; conditions: Record<string, any>; scope?: "bot" | "global" },
  ) => void;
  deciding: boolean;
}) {
  const t = useThemeTokens();
  const argsPreview = JSON.stringify(approval.arguments, null, 2);
  const createdAt = new Date(approval.created_at).toLocaleString();
  const isPending = approval.status === "pending";
  const { data: suggestions } = useApprovalSuggestions(isPending ? approval.id : undefined);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "16px 20px",
        background: t.inputBg,
        borderRadius: 10,
        border: isPending ? `1px solid ${t.warningBorder}` : `1px solid ${t.surfaceOverlay}`,
        width: "100%",
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <StatusIcon status={approval.status} />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: t.text,
            flex: 1,
            fontFamily: "monospace",
          }}
        >
          {approval.tool_name}
        </span>
        <StatusBadge status={approval.status} />
      </div>

      <div
        style={{
          display: "flex", flexDirection: "row",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span
          style={{
            padding: "1px 6px",
            borderRadius: 3,
            fontSize: 10,
            fontWeight: 600,
            background: t.accentSubtle,
            color: t.accent,
          }}
        >
          {approval.bot_id}
        </span>
        <span style={{ fontSize: 11, color: t.textDim }}>{approval.tool_type}</span>
        <span style={{ fontSize: 11, color: t.textDim }}>{createdAt}</span>
      </div>

      {approval.reason && (
        <div style={{ fontSize: 12, color: t.warningMuted }}>{approval.reason}</div>
      )}

      <pre
        style={{
          padding: "8px 12px",
          borderRadius: 6,
          background: t.surface,
          border: `1px solid ${t.surfaceRaised}`,
          fontSize: 11,
          color: t.textMuted,
          fontFamily: "monospace",
          overflow: "auto",
          maxHeight: 120,
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
        }}
      >
        {argsPreview}
      </pre>

      {approval.decided_by && (
        <div style={{ fontSize: 11, color: t.textDim }}>
          Decided by: {approval.decided_by}
          {approval.decided_at &&
            ` at ${new Date(approval.decided_at).toLocaleString()}`}
        </div>
      )}

      {isPending && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
          {/* Primary actions: Allow always + Approve this run + Deny */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() =>
                onDecideWithRule(approval.id, {
                  tool_name: approval.tool_name,
                  conditions: {},
                  scope: "bot",
                })
              }
              disabled={deciding}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 6,
                background: t.successSubtle,
                border: `1px solid ${t.success}`,
                cursor: deciding ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                color: t.success,
                opacity: deciding ? 0.5 : 1,
              }}
            >
              <ShieldCheck size={14} /> Allow always
            </button>
            <button
              onClick={() => onDecide(approval.id, true)}
              disabled={deciding}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 6,
                background: t.successSubtle,
                border: `1px solid ${t.successBorder}`,
                cursor: deciding ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 500,
                color: t.success,
                opacity: deciding ? 0.5 : 1,
              }}
            >
              <Play size={14} /> Approve this run
            </button>
            <button
              onClick={() => onDecide(approval.id, false)}
              disabled={deciding}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 6,
                background: t.dangerSubtle,
                border: `1px solid ${t.dangerBorder}`,
                cursor: deciding ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                color: t.danger,
                opacity: deciding ? 0.5 : 1,
              }}
            >
              <ThumbsDown size={14} /> Deny
            </button>
          </div>
          {/* Smart suggestions (broadest-first from API) */}
          {suggestions && suggestions.length > 0 && (
            <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              <span style={{ fontSize: 11, color: t.textDim, alignSelf: "center" }}>
                Approve & create rule:
              </span>
              {suggestions.map((s, i) => (
                <SuggestionButton
                  key={i}
                  suggestion={s}
                  disabled={deciding}
                  onClick={() =>
                    onDecideWithRule(approval.id, {
                      tool_name: s.tool_name,
                      conditions: s.conditions,
                      scope: s.scope,
                    })
                  }
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ApprovalsScreen() {
  const t = useThemeTokens();
  const [statusFilter, setStatusFilter] = useState("all");
  const { data: approvals, isLoading } = useApprovals(
    undefined,
    statusFilter === "all" ? undefined : statusFilter
  );
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const decideMut = useDecideApproval();

  const pendingCount = approvals?.filter((a) => a.status === "pending").length ?? 0;

  const handleDecide = (approvalId: string, approved: boolean) => {
    decideMut.mutate({
      approvalId,
      data: { approved, decided_by: "ui:admin" },
    });
  };

  const handleDecideWithRule = (
    approvalId: string,
    rule: { tool_name: string; conditions: Record<string, any>; scope?: "bot" | "global" },
  ) => {
    decideMut.mutate({
      approvalId,
      data: {
        approved: true,
        decided_by: "ui:admin",
        create_rule: rule,
      },
    });
  };

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Approvals"
        subtitle={pendingCount > 0 ? `${pendingCount} pending` : undefined}
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
        <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
          <div style={{ marginBottom: 16 }}>
            <TabBar
              tabs={STATUS_TABS}
              active={statusFilter}
              onChange={setStatusFilter}
            />
          </div>

          {isLoading ? (
            <div className="items-center justify-center py-20">
              <Spinner color={t.accent} />
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isWide
                  ? "repeat(auto-fill, minmax(420px, 1fr))"
                  : "1fr",
                gap: 12,
              }}
            >
              {approvals?.map((a) => (
                <ApprovalCard
                  key={a.id}
                  approval={a}
                  onDecide={handleDecide}
                  onDecideWithRule={handleDecideWithRule}
                  deciding={decideMut.isPending}
                />
              ))}
              {approvals?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: t.textDim,
                    fontSize: 14,
                  }}
                >
                  No approvals{statusFilter !== "all" ? ` with status "${statusFilter}"` : ""}.
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
