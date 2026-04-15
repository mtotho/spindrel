import { useMemo } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useNavigate } from "react-router-dom";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useToolPolicies,
  usePolicySettings,
} from "@/src/api/hooks/useToolPolicies";

export function BotToolPoliciesSection({ botId }: { botId: string }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
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
        background: !isEnabled ? t.surfaceOverlay : isDeny ? t.dangerSubtle : t.successSubtle,
        border: !isEnabled ? `1px solid ${t.surfaceBorder}` : isDeny ? `1px solid ${t.dangerBorder}` : `1px solid ${t.success}22`,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: !isEnabled ? t.textMuted : isDeny ? t.danger : t.success }}>
          {!isEnabled
            ? "Policy engine is disabled — all tool calls are allowed"
            : isDeny
              ? "Default: DENY — this bot needs explicit allow rules to use tools"
              : "Default: ALLOW — this bot can use all tools unless blocked by a rule"}
        </div>
        {isEnabled && applicableRules.length === 0 && isDeny && (
          <div style={{ fontSize: 12, color: t.warning, marginTop: 4 }}>
            No rules apply to this bot. All tool calls will be blocked.
          </div>
        )}
      </div>

      {/* Summary */}
      {applicableRules.length > 0 && (
        <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: t.success }}>{allowCount} allow</span>
          <span style={{ fontSize: 12, color: t.danger }}>{denyCount} deny</span>
          <span style={{ fontSize: 12, color: t.warning }}>{approvalCount} require approval</span>
          <span style={{ fontSize: 12, color: t.textDim }}>
            ({botSpecific.length} bot-specific, {globalRules.length} global)
          </span>
        </div>
      )}

      {/* Rule list */}
      {isLoading ? (
        <Spinner color={t.accent} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {applicableRules
            .sort((a, b) => a.priority - b.priority)
            .map((r) => {
              const actionColor = r.action === "allow" ? t.success : r.action === "deny" ? t.danger : t.warning;
              return (
                <button
                  key={r.id}
                  onClick={() => navigate(`/admin/tool-policies/${r.id}` as any)}
                  style={{
                    display: "flex", flexDirection: "row",
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
                    background: r.bot_id ? t.accentSubtle : t.purpleSubtle,
                    color: r.bot_id ? t.accent : t.purple,
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
      <div style={{ display: "flex", flexDirection: "row", gap: 8, marginTop: 4 }}>
        <button
          onClick={() => navigate(`/admin/tool-policies/new?bot_id=${botId}` as any)}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            padding: "8px 14px", borderRadius: 6,
            background: t.accent, border: "none",
            cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#fff",
          }}
        >
          Add Rule for This Bot
        </button>
        <button
          onClick={() => navigate("/admin/tool-policies" as any)}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
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
