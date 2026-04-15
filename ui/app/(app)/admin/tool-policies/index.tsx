
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Plus, Shield, ShieldAlert, ShieldCheck, ShieldX, AlertTriangle } from "lucide-react";
import {
  useToolPolicies,
  usePolicySettings,
  useUpdatePolicySettings,
  type ToolPolicyRule,
} from "@/src/api/hooks/useToolPolicies";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Toggle } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function ActionBadge({ action }: { action: string }) {
  const t = useThemeTokens();
  const config: Record<string, { bg: string; color: string; label: string }> = {
    allow: {
      bg: t.successSubtle,
      color: t.success,
      label: "Allow",
    },
    deny: {
      bg: t.dangerSubtle,
      color: t.danger,
      label: "Deny",
    },
    require_approval: {
      bg: t.warningSubtle,
      color: t.warning,
      label: "Require Approval",
    },
  };
  const c = config[action] || config.deny;
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.color,
        whiteSpace: "nowrap",
      }}
    >
      {c.label}
    </span>
  );
}

function PolicyCard({
  rule,
  onClick,
}: {
  rule: ToolPolicyRule;
  onClick: () => void;
}) {
  const t = useThemeTokens();
  const Icon =
    rule.action === "allow"
      ? ShieldCheck
      : rule.action === "deny"
      ? ShieldX
      : ShieldAlert;
  const iconColor =
    rule.action === "allow"
      ? t.success
      : rule.action === "deny"
      ? t.danger
      : t.warningMuted;

  const hasConditions =
    rule.conditions &&
    Object.keys(rule.conditions).length > 0 &&
    rule.conditions.arguments &&
    Object.keys(rule.conditions.arguments).length > 0;

  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "16px 20px",
        background: t.inputBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceOverlay}`,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        opacity: rule.enabled ? 1 : 0.5,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Icon size={16} color={iconColor} />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: t.text,
            flex: 1,
            fontFamily: "monospace",
          }}
        >
          {rule.tool_name}
        </span>
        <ActionBadge action={rule.action} />
      </div>

      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: t.textDim }}>
          Priority: {rule.priority}
        </span>
        {rule.bot_id ? (
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
            bot:{rule.bot_id}
          </span>
        ) : (
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              fontSize: 10,
              fontWeight: 600,
              background: t.purpleSubtle,
              color: t.purple,
            }}
          >
            global
          </span>
        )}
        {!rule.enabled && (
          <span style={{ fontSize: 10, color: t.textDim }}>disabled</span>
        )}
      </div>

      {rule.reason && (
        <div style={{ fontSize: 12, color: t.textMuted }}>{rule.reason}</div>
      )}

      {hasConditions && (
        <div
          style={{
            fontSize: 11,
            color: t.textDim,
            fontFamily: "monospace",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {JSON.stringify(rule.conditions.arguments)}
        </div>
      )}
    </button>
  );
}

function SettingsPanel() {
  const t = useThemeTokens();
  const { data: policySettings, isLoading } = usePolicySettings();
  const updateMut = useUpdatePolicySettings();

  if (isLoading || !policySettings) return null;

  const action = policySettings.default_action;
  const borderColor =
    action === "deny" ? t.dangerBorder
    : action === "require_approval" ? t.warningSubtle
    : t.successSubtle;
  const bgColor =
    action === "deny" ? t.dangerSubtle
    : action === "require_approval" ? t.warningSubtle
    : t.successSubtle;
  const iconColor =
    !policySettings.enabled ? t.textDim
    : action === "deny" ? t.danger
    : action === "require_approval" ? t.warningMuted
    : t.success;
  const description =
    !policySettings.enabled
      ? "Policy engine is off — all tool calls are permitted without checks"
      : action === "deny"
      ? "Default: DENY — all tool calls are blocked unless explicitly allowed by a rule"
      : action === "require_approval"
      ? "Default: REQUIRE APPROVAL — all tool calls need human approval unless explicitly allowed by a rule"
      : "Default: ALLOW — all tool calls are permitted unless blocked by a rule";

  const actions = [
    { key: "allow", label: "Allow", color: t.success, activeColor: t.successSubtle, borderActive: t.success },
    { key: "require_approval", label: "Require Approval", color: t.warning, activeColor: t.warningSubtle, borderActive: t.warning },
    { key: "deny", label: "Deny", color: t.danger, activeColor: t.dangerSubtle, borderActive: t.dangerBorder },
  ] as const;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: "16px 20px",
        borderRadius: 10,
        background: bgColor,
        border: `1px solid ${borderColor}`,
        marginBottom: 16,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
        <Shield size={18} color={iconColor} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
            Policy Engine {policySettings.enabled ? "Active" : "Disabled"}
          </div>
          <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
            {description}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "row", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <Toggle
          value={policySettings.enabled}
          onChange={(v) => updateMut.mutate({ enabled: v })}
          label="Enabled"
        />
        {policySettings.enabled && (
          <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: t.textMuted }}>Default action:</span>
            {actions.map((a) => {
              const isActive = action === a.key;
              return (
                <button
                  key={a.key}
                  onClick={() => updateMut.mutate({ default_action: a.key })}
                  style={{
                    padding: "4px 12px",
                    borderRadius: 5,
                    fontSize: 12,
                    fontWeight: 600,
                    border: "1px solid",
                    cursor: "pointer",
                    background: isActive ? a.activeColor : "transparent",
                    borderColor: isActive ? a.borderActive : t.surfaceBorder,
                    color: isActive ? a.color : t.textDim,
                  }}
                >
                  {a.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ToolPoliciesScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: rules, isLoading } = useToolPolicies();
  const { data: policySettings } = usePolicySettings();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;

  const defaultAction = policySettings?.default_action;
  const isBlockingDefault = defaultAction === "deny" || defaultAction === "require_approval";
  const allowRules = rules?.filter((r) => r.action === "allow" && r.enabled) || [];
  const denyRules = rules?.filter((r) => r.action === "deny" && r.enabled) || [];
  const approvalRules = rules?.filter((r) => r.action === "require_approval" && r.enabled) || [];

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Tool Policies"
        right={
          <button
            onClick={() =>
              navigate("/admin/tool-policies/new")
            }
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              borderRadius: 6,
              background: t.accent,
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
              color: "#fff",
            }}
          >
            <Plus size={14} /> New Rule
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
        <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
          {/* Settings panel */}
          <SettingsPanel />

          {/* How it works */}
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 8,
              background: t.accentSubtle,
              border: `1px solid ${t.accentBorder}`,
              marginBottom: 16,
              fontSize: 12,
              color: t.textMuted,
              lineHeight: 1.6,
            }}
          >
            <div style={{ fontWeight: 700, color: t.accent, marginBottom: 4 }}>How it works</div>
            When a bot tries to call a tool, the policy engine evaluates rules in priority order
            (lowest number first). The <strong style={{ color: t.text }}>first matching rule wins</strong>.
            Bot-specific rules take precedence over global rules at the same priority.
            If no rule matches, the <strong style={{ color: t.text }}>default action</strong> above applies.
            <div style={{ marginTop: 8 }}>
              <strong style={{ color: t.success }}>Allow</strong> — tool call proceeds normally.{" "}
              <strong style={{ color: t.danger }}>Deny</strong> — blocked, bot sees an error.{" "}
              <strong style={{ color: t.warning }}>Require Approval</strong> — paused until a human approves via the Approvals page or Slack.
            </div>
            {isBlockingDefault && !rules?.length && (
              <div style={{
                marginTop: 10,
                padding: "8px 12px",
                borderRadius: 6,
                background: t.warningSubtle,
                border: `1px solid ${t.warningBorder}`,
                color: t.warning,
              }}>
                <AlertTriangle size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: 4 }} />
                <strong>Default is {defaultAction === "deny" ? "DENY" : "REQUIRE APPROVAL"} and you have no rules.</strong>{" "}
                {defaultAction === "deny" ? "All bot tool calls will be blocked." : "All bot tool calls will require human approval."}
                {" "}Create an <strong>allow</strong> rule (e.g. tool name <code style={{ background: t.surfaceOverlay, padding: "1px 4px", borderRadius: 3 }}>*</code> for a specific bot) to unblock.
              </div>
            )}
          </div>

          {/* Summary badges */}
          {rules && rules.length > 0 && (
            <div style={{ display: "flex", flexDirection: "row", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: t.success }}>
                {allowRules.length} allow
              </span>
              <span style={{ fontSize: 12, color: t.danger }}>
                {denyRules.length} deny
              </span>
              <span style={{ fontSize: 12, color: t.warning }}>
                {approvalRules.length} require approval
              </span>
              <span style={{ fontSize: 12, color: t.textDim }}>
                {rules.length} total rules
              </span>
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner />
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isWide
                  ? "repeat(auto-fill, minmax(380px, 1fr))"
                  : "1fr",
                gap: 12,
              }}
            >
              {rules?.map((r) => (
                <PolicyCard
                  key={r.id}
                  rule={r}
                  onClick={() =>
                    navigate(`/admin/tool-policies/${r.id}`)
                  }
                />
              ))}
              {rules?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: t.textDim,
                    fontSize: 14,
                  }}
                >
                  No policy rules yet.
                  {defaultAction === "deny"
                    ? " All bot tool calls are currently BLOCKED."
                    : defaultAction === "require_approval"
                    ? " All bot tool calls currently require APPROVAL."
                    : " All tool calls are currently allowed."}
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
