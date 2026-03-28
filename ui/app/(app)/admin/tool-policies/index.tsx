import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, Shield, ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import {
  useToolPolicies,
  type ToolPolicyRule,
} from "@/src/api/hooks/useToolPolicies";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

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

export default function ToolPoliciesScreen() {
  const router = useRouter();
  const { data: rules, isLoading } = useToolPolicies();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

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
          {/* Description */}
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 8,
              background: "rgba(59,130,246,0.06)",
              border: "1px solid rgba(59,130,246,0.12)",
              marginBottom: 16,
              fontSize: 12,
              color: "#93c5fd",
              lineHeight: 1.5,
            }}
          >
            Tool policies control what bots can do. Rules are evaluated in
            priority order (lowest first) — first match wins. Use{" "}
            <strong>deny</strong> to block, <strong>require_approval</strong> to
            pause for human approval, or <strong>allow</strong> to explicitly
            permit.
          </div>

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
                  No policy rules yet. All tool calls are allowed by default.
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
