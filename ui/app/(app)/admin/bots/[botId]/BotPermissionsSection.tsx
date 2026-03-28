import { ActivityIndicator } from "react-native";
import { Check } from "lucide-react";
import { useApiKeyScopes } from "@/src/api/hooks/useApiKeys";
import { useThemeTokens } from "@/src/theme/tokens";

const API_DOCS_MODES = [
  { value: "", label: "Disabled", description: "No API docs injected into context" },
  { value: "on_demand", label: "On Demand", description: "Short hint injected; bot runs `agent docs` when needed" },
  { value: "rag", label: "RAG", description: "Full docs injected only when the message mentions API-related keywords" },
  { value: "pinned", label: "Pinned", description: "Full docs injected every turn (~1K tokens)" },
];

export function BotPermissionsSection({
  permissions,
  onChange,
  docsMode,
  onDocsModeChange,
}: {
  permissions: string[];
  onChange: (scopes: string[]) => void;
  docsMode: string | null | undefined;
  onDocsModeChange: (mode: string | null) => void;
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
        Control which API endpoints this bot can access when running inside a workspace or sandbox.
        A scoped API key is automatically created and injected into the bot's container environment.
      </div>

      {hasAdmin && (
        <div style={{
          padding: "8px 12px", borderRadius: 6,
          background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)",
          fontSize: 12, color: "#fca5a5",
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
                          ? isAdmin ? "1px solid rgba(239,68,68,0.4)" : "1px solid rgba(59,130,246,0.4)"
                          : `1px solid ${t.surfaceBorder}`,
                        background: checked
                          ? isAdmin ? "rgba(239,68,68,0.1)" : "rgba(59,130,246,0.1)"
                          : "transparent",
                        cursor: "pointer", fontSize: 12,
                        color: checked ? (isAdmin ? "#fca5a5" : "#93c5fd") : t.textDim,
                        fontWeight: checked ? 600 : 400,
                      }}>
                        <span style={{
                          width: 14, height: 14, borderRadius: 3,
                          border: checked ? "none" : `1px solid ${t.surfaceBorder}`,
                          background: checked ? (isAdmin ? "#ef4444" : "#3b82f6") : "transparent",
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
        <ActivityIndicator color="#3b82f6" />
      )}

      {permissions.length > 0 && (
        <>
          <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
            {permissions.length} scope{permissions.length !== 1 ? "s" : ""} selected.
            The bot's scoped key will be updated on save.
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{
              fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6,
              textTransform: "uppercase", letterSpacing: 0.5,
            }}>
              API Docs Injection
            </div>
            <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>
              How API documentation for the bot's available endpoints is included in context.
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {API_DOCS_MODES.map((m) => {
                const active = (docsMode || "") === m.value;
                return (
                  <button
                    key={m.value}
                    onClick={() => onDocsModeChange(m.value || null)}
                    title={m.description}
                    style={{
                      padding: "5px 12px", borderRadius: 5, fontSize: 12, cursor: "pointer",
                      border: active ? "1px solid rgba(59,130,246,0.4)" : `1px solid ${t.surfaceBorder}`,
                      background: active ? "rgba(59,130,246,0.1)" : "transparent",
                      color: active ? "#93c5fd" : t.textDim,
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
            {docsMode && (
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
                {API_DOCS_MODES.find((m) => m.value === docsMode)?.description}
              </div>
            )}
          </div>
        </>
      )}
      {permissions.length === 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>
          No scopes selected. The bot will use the server's default API key in containers.
        </div>
      )}
    </div>
  );
}
