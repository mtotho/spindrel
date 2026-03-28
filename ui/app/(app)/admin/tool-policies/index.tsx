import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, Shield, ShieldAlert, ShieldCheck, ShieldX, AlertTriangle } from "lucide-react";
import {
  useToolPolicies,
  usePolicySettings,
  useUpdatePolicySettings,
  type ToolPolicyRule,
} from "@/src/api/hooks/useToolPolicies";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { Toggle } from "@/src/components/shared/FormControls";

function ActionBadge({ action }: { action: string }) {
  const config: Record<string, { bg: string; color: string; label: string }> = {
    allow: {
      bg: "rgba(34,197,94,0.12)",
      color: "#86efac",
      label: "Allow",
    },
    deny: {
      bg: "rgba(239,68,68,0.12)",
      color: "#fca5a5",
      label: "Deny",
    },
    require_approval: {
      bg: "rgba(251,191,36,0.12)",
      color: "#fde68a",
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
  onPress,
}: {
  rule: ToolPolicyRule;
  onPress: () => void;
}) {
  const Icon =
    rule.action === "allow"
      ? ShieldCheck
      : rule.action === "deny"
      ? ShieldX
      : ShieldAlert;
  const iconColor =
    rule.action === "allow"
      ? "#22c55e"
      : rule.action === "deny"
      ? "#ef4444"
      : "#fbbf24";

  const hasConditions =
    rule.conditions &&
    Object.keys(rule.conditions).length > 0 &&
    rule.conditions.arguments &&
    Object.keys(rule.conditions.arguments).length > 0;

  return (
    <button
      onClick={onPress}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "16px 20px",
        background: "#111",
        borderRadius: 10,
        border: "1px solid #222",
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        opacity: rule.enabled ? 1 : 0.5,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={16} color={iconColor} />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "#e5e5e5",
            flex: 1,
            fontFamily: "monospace",
          }}
        >
          {rule.tool_name}
        </span>
        <ActionBadge action={rule.action} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#666" }}>
          Priority: {rule.priority}
        </span>
        {rule.bot_id ? (
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              fontSize: 10,
              fontWeight: 600,
              background: "rgba(59,130,246,0.12)",
              color: "#93c5fd",
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
              background: "rgba(168,85,247,0.12)",
              color: "#c4b5fd",
            }}
          >
            global
          </span>
        )}
        {!rule.enabled && (
          <span style={{ fontSize: 10, color: "#555" }}>disabled</span>
        )}
      </div>

      {rule.reason && (
        <div style={{ fontSize: 12, color: "#888" }}>{rule.reason}</div>
      )}

      {hasConditions && (
        <div
          style={{
            fontSize: 11,
            color: "#555",
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
  const { data: policySettings, isLoading } = usePolicySettings();
  const updateMut = useUpdatePolicySettings();

  if (isLoading || !policySettings) return null;

  const isDeny = policySettings.default_action === "deny";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: "16px 20px",
        borderRadius: 10,
        background: isDeny ? "rgba(239,68,68,0.04)" : "rgba(34,197,94,0.04)",
        border: isDeny
          ? "1px solid rgba(239,68,68,0.15)"
          : "1px solid rgba(34,197,94,0.15)",
        marginBottom: 16,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Shield size={18} color={policySettings.enabled ? (isDeny ? "#ef4444" : "#22c55e") : "#555"} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#e5e5e5" }}>
            Policy Engine {policySettings.enabled ? "Active" : "Disabled"}
          </div>
          <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>
            {policySettings.enabled
              ? isDeny
                ? "Default: DENY — all tool calls are blocked unless explicitly allowed by a rule"
                : "Default: ALLOW — all tool calls are permitted unless blocked by a rule"
              : "Policy engine is off — all tool calls are permitted without checks"}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <Toggle
          value={policySettings.enabled}
          onChange={(v) => updateMut.mutate({ enabled: v })}
          label="Enabled"
        />
        {policySettings.enabled && (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "#888" }}>Default action:</span>
            <button
              onClick={() => updateMut.mutate({ default_action: "deny" })}
              style={{
                padding: "4px 12px",
                borderRadius: 5,
                fontSize: 12,
                fontWeight: 600,
                border: "1px solid",
                cursor: "pointer",
                background: isDeny ? "rgba(239,68,68,0.15)" : "transparent",
                borderColor: isDeny ? "rgba(239,68,68,0.3)" : "#333",
                color: isDeny ? "#fca5a5" : "#666",
              }}
            >
              Deny
            </button>
            <button
              onClick={() => updateMut.mutate({ default_action: "allow" })}
              style={{
                padding: "4px 12px",
                borderRadius: 5,
                fontSize: 12,
                fontWeight: 600,
                border: "1px solid",
                cursor: "pointer",
                background: !isDeny ? "rgba(34,197,94,0.15)" : "transparent",
                borderColor: !isDeny ? "rgba(34,197,94,0.3)" : "#333",
                color: !isDeny ? "#86efac" : "#666",
              }}
            >
              Allow
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ToolPoliciesScreen() {
  const router = useRouter();
  const { data: rules, isLoading } = useToolPolicies();
  const { data: policySettings } = usePolicySettings();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const isDeny = policySettings?.default_action === "deny";
  const allowRules = rules?.filter((r) => r.action === "allow" && r.enabled) || [];
  const denyRules = rules?.filter((r) => r.action === "deny" && r.enabled) || [];
  const approvalRules = rules?.filter((r) => r.action === "require_approval" && r.enabled) || [];

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Tool Policies"
        right={
          <button
            onClick={() =>
              router.push("/admin/tool-policies/new" as any)
            }
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              borderRadius: 6,
              background: "#3b82f6",
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
              background: "rgba(59,130,246,0.04)",
              border: "1px solid rgba(59,130,246,0.1)",
              marginBottom: 16,
              fontSize: 12,
              color: "#888",
              lineHeight: 1.6,
            }}
          >
            <div style={{ fontWeight: 700, color: "#93c5fd", marginBottom: 4 }}>How it works</div>
            When a bot tries to call a tool, the policy engine evaluates rules in priority order
            (lowest number first). The <strong style={{ color: "#e5e5e5" }}>first matching rule wins</strong>.
            Bot-specific rules take precedence over global rules at the same priority.
            If no rule matches, the <strong style={{ color: "#e5e5e5" }}>default action</strong> above applies.
            <div style={{ marginTop: 8 }}>
              <strong style={{ color: "#86efac" }}>Allow</strong> — tool call proceeds normally.{" "}
              <strong style={{ color: "#fca5a5" }}>Deny</strong> — blocked, bot sees an error.{" "}
              <strong style={{ color: "#fde68a" }}>Require Approval</strong> — paused until a human approves via the Approvals page or Slack.
            </div>
            {isDeny && !rules?.length && (
              <div style={{
                marginTop: 10,
                padding: "8px 12px",
                borderRadius: 6,
                background: "rgba(251,191,36,0.08)",
                border: "1px solid rgba(251,191,36,0.15)",
                color: "#fde68a",
              }}>
                <AlertTriangle size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: 4 }} />
                <strong>Default is DENY and you have no rules.</strong> All bot tool calls will be blocked.
                Create an <strong>allow</strong> rule (e.g. tool name <code style={{ background: "#222", padding: "1px 4px", borderRadius: 3 }}>*</code> for a specific bot) to unblock.
              </div>
            )}
          </div>

          {/* Summary badges */}
          {rules && rules.length > 0 && (
            <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: "#86efac" }}>
                {allowRules.length} allow
              </span>
              <span style={{ fontSize: 12, color: "#fca5a5" }}>
                {denyRules.length} deny
              </span>
              <span style={{ fontSize: 12, color: "#fde68a" }}>
                {approvalRules.length} require approval
              </span>
              <span style={{ fontSize: 12, color: "#555" }}>
                {rules.length} total rules
              </span>
            </div>
          )}

          {isLoading ? (
            <View className="items-center justify-center py-20">
              <ActivityIndicator color="#3b82f6" />
            </View>
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
                  onPress={() =>
                    router.push(`/admin/tool-policies/${r.id}` as any)
                  }
                />
              ))}
              {rules?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: "#555",
                    fontSize: 14,
                  }}
                >
                  No policy rules yet.
                  {isDeny
                    ? " All bot tool calls are currently BLOCKED."
                    : " All tool calls are currently allowed."}
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
