import { ActivityIndicator } from "react-native";
import { Check } from "lucide-react";
import { useApiKeyScopes } from "@/src/api/hooks/useApiKeys";
import { useThemeTokens } from "@/src/theme/tokens";

export function BotPermissionsSection({
  permissions,
  onChange,
}: {
  permissions: string[];
  onChange: (scopes: string[]) => void;
}) {
  const t = useThemeTokens();
  const { data: scopeGroups } = useApiKeyScopes();
  const set = new Set(permissions);

  const toggle = (scope: string) => {
    const next = new Set(set);
    if (next.has(scope)) next.delete(scope);
    else next.add(scope);
    onChange(Array.from(next));
  };

  const hasAdmin = set.has("admin");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Permissions</div>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Control which API endpoints this bot can access. A scoped API key is automatically
        created. When permissions are set, the bot gets <code style={{ color: t.textMuted }}>list_api_endpoints</code> and{" "}
        <code style={{ color: t.textMuted }}>call_api</code> tools pinned to its context.
      </div>

      {hasAdmin && (
        <div style={{
          padding: "8px 12px", borderRadius: 6,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          fontSize: 12, color: t.danger,
        }}>
          Warning: admin scope grants full access to all endpoints including admin panel.
        </div>
      )}

      {scopeGroups ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {Object.entries(scopeGroups.groups).map(([group, groupInfo]) => {
            const scopes = groupInfo.scopes;
            return (
              <div key={group}>
                <div style={{
                  fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 2,
                  textTransform: "uppercase", letterSpacing: 0.5,
                }}>
                  {group}
                </div>
                <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>
                  {groupInfo.description}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {scopes.map((scope) => {
                    const checked = set.has(scope);
                    const isAdmin = scope === "admin";
                    const desc = scopeGroups.descriptions?.[scope];
                    return (
                      <button key={scope} onClick={() => toggle(scope)} title={desc} style={{
                        display: "flex", alignItems: "center", gap: 6,
                        padding: "4px 10px", borderRadius: 5,
                        border: checked
                          ? isAdmin ? `1px solid ${t.dangerBorder}` : `1px solid ${t.accentBorder}`
                          : `1px solid ${t.surfaceBorder}`,
                        background: checked
                          ? isAdmin ? t.dangerSubtle : t.accentSubtle
                          : "transparent",
                        cursor: "pointer", fontSize: 12,
                        color: checked ? (isAdmin ? t.danger : t.accent) : t.textDim,
                        fontWeight: checked ? 600 : 400,
                      }}>
                        <span style={{
                          width: 14, height: 14, borderRadius: 3,
                          border: checked ? "none" : `1px solid ${t.surfaceBorder}`,
                          background: checked ? (isAdmin ? t.dangerMuted : t.accent) : "transparent",
                          display: "flex", alignItems: "center", justifyContent: "center",
                        }}>
                          {checked && <Check size={10} color="#fff" strokeWidth={3} />}
                        </span>
                        {scope}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <ActivityIndicator color={t.accent} />
      )}

      {permissions.length > 0 && (
        <div style={{
          marginTop: 12, padding: "10px 12px", borderRadius: 6,
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.accent, marginBottom: 4 }}>
            API Access Tools
          </div>
          <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.5 }}>
            The bot will automatically get <code style={{ color: t.textMuted }}>list_api_endpoints</code> and{" "}
            <code style={{ color: t.textMuted }}>call_api</code> tools pinned to its context.
            These tools let it discover and call server API endpoints filtered to the {permissions.length} scope{permissions.length !== 1 ? "s" : ""} selected above.
            Requests run in-process with full auth — no sandbox or CLI needed.
          </div>
        </div>
      )}
      {permissions.length === 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
          No scopes selected. The bot will not have API access tools.
        </div>
      )}
    </div>
  );
}
