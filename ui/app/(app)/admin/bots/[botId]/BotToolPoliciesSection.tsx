import { useMemo } from "react";
import { ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useToolPolicies,
  usePolicySettings,
} from "@/src/api/hooks/useToolPolicies";

export function BotToolPoliciesSection({ botId }: { botId: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: allRules, isLoading } = useToolPolicies();
  const { data: policySettings } = usePolicySettings();

  const isEnabled = policySettings?.enabled !== false;
  const isDeny = policySettings?.default_action === "deny";

  // Rules that apply to this bot: bot-specific + global
  const applicableRules = useMemo(() => {
    if (!allRules) return [];
    return allRules.filter((r) => r.bot_id === botId || r.bot_id === null);
  }, [allRules, botId]);

  const botSpecific = applicableRules.filter((r) => r.bot_id === botId);
  const globalRules = applicableRules.filter((r) => r.bot_id === null);
  const allowCount = applicableRules.filter((r) => r.action === "allow" && r.enabled).length;
  const denyCount = applicableRules.filter((r) => r.action === "deny" && r.enabled).length;
  const approvalCount = applicableRules.filter((r) => r.action === "require_approval" && r.enabled).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Tool Policies</div>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Rules that control which tools this bot can call. Bot-specific rules take priority over global rules at the same priority level.
      </div>

      {/* Status banner */}
      <div style={{
        padding: "10px 14px",
        borderRadius: 8,
        background: !isEnabled ? "rgba(107,114,128,0.06)" : isDeny ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)",
        border: !isEnabled ? "1px solid rgba(107,114,128,0.12)" : isDeny ? "1px solid rgba(239,68,68,0.12)" : "1px solid rgba(34,197,94,0.12)",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: !isEnabled ? t.textMuted : isDeny ? "#fca5a5" : "#86efac" }}>
          {!isEnabled
            ? "Policy engine is disabled — all tool calls are allowed"
            : isDeny
              ? "Default: DENY — this bot needs explicit allow rules to use tools"
              : "Default: ALLOW — this bot can use all tools unless blocked by a rule"}
        </div>
        {isEnabled && applicableRules.length === 0 && isDeny && (
          <div style={{ fontSize: 12, color: "#fde68a", marginTop: 4 }}>
            No rules apply to this bot. All tool calls will be blocked.
          </div>
        )}
      </div>

      {/* Summary */}
      {applicableRules.length > 0 && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: "#86efac" }}>{allowCount} allow</span>
          <span style={{ fontSize: 12, color: "#fca5a5" }}>{denyCount} deny</span>
          <span style={{ fontSize: 12, color: "#fde68a" }}>{approvalCount} require approval</span>
          <span style={{ fontSize: 12, color: t.textDim }}>
            ({botSpecific.length} bot-specific, {globalRules.length} global)
          </span>
        </div>
      )}

      {/* Rule list */}
      {isLoading ? (
        <ActivityIndicator color="#3b82f6" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {applicableRules
            .sort((a, b) => a.priority - b.priority)
            .map((r) => {
              const actionColor = r.action === "allow" ? "#86efac" : r.action === "deny" ? "#fca5a5" : "#fde68a";
              return (
                <button
                  key={r.id}
                  onClick={() => router.push(`/admin/tool-policies/${r.id}` as any)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 12px",
                    background: t.inputBg,
                    borderRadius: 6,
                    border: `1px solid ${t.surfaceRaised}`,
                    cursor: "pointer",
                    textAlign: "left",
                    width: "100%",
                    opacity: r.enabled ? 1 : 0.5,
                  }}
                >
                  <span style={{ fontSize: 12, fontFamily: "monospace", color: t.text, flex: 1 }}>
                    {r.tool_name}
                  </span>
                  <span style={{
                    fontSize: 10, fontWeight: 600,
                    padding: "1px 6px", borderRadius: 3,
                    background: r.bot_id ? "rgba(59,130,246,0.12)" : "rgba(168,85,247,0.12)",
                    color: r.bot_id ? "#93c5fd" : "#c4b5fd",
                  }}>
                    {r.bot_id ? "bot" : "global"}
                  </span>
                  <span style={{
                    fontSize: 10, fontWeight: 600,
                    padding: "2px 6px", borderRadius: 3,
                    background: `${actionColor}15`,
                    color: actionColor,
                  }}>
                    {r.action}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim }}>p:{r.priority}</span>
                </button>
              );
            })}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button
          onClick={() => router.push(`/admin/tool-policies/new?bot_id=${botId}` as any)}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "8px 14px", borderRadius: 6,
            background: t.accent, border: "none",
            cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#fff",
          }}
        >
          Add Rule for This Bot
        </button>
        <button
          onClick={() => router.push("/admin/tool-policies" as any)}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "8px 14px", borderRadius: 6,
            background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
            cursor: "pointer", fontSize: 12, color: t.textMuted,
          }}
        >
          Manage All Policies
        </button>
      </div>
    </div>
  );
}
