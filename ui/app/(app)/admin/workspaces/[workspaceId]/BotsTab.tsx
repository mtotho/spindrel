import { useUpdateWorkspaceBot } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import type { WorkspaceBot } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface BotsTabProps {
  workspaceId: string;
  bots: WorkspaceBot[];
  writeProtectedPaths: string[];
}

// ---------------------------------------------------------------------------
// Bots tab: shows auto-enrolled bots with role/write-access editing.
// Single-workspace mode: every bot is a permanent member of the default
// workspace via the bootstrap loop, so this tab does NOT expose add/remove
// affordances. It only edits per-membership config (role, write_access).
// ---------------------------------------------------------------------------
export function BotsTab({ workspaceId, bots, writeProtectedPaths }: BotsTabProps) {
  const t = useThemeTokens();
  const updateBot = useUpdateWorkspaceBot(workspaceId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Section
        title="Connected Bots"
        description="All bots are auto-enrolled into the workspace. Orchestrators see all files; members are scoped to /workspace/bots/<bot_id>/."
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {bots.length === 0 && (
            <div style={{ color: t.textDim, fontSize: 12 }}>No bots connected.</div>
          )}
          {bots.map((b) => {
            const botWriteAccess = b.write_access || [];
            const toggleWriteAccess = (path: string) => {
              const has = botWriteAccess.includes(path);
              const next = has ? botWriteAccess.filter((p) => p !== path) : [...botWriteAccess, path];
              updateBot.mutate({ bot_id: b.bot_id, write_access: next });
            };
            return (
              <div key={b.bot_id} style={{
                display: "flex", flexDirection: "column", gap: 6,
                padding: "8px 12px", background: t.surface, borderRadius: 8,
                border: `1px solid ${t.surfaceRaised}`,
              }}>
                <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <span style={{
                    fontSize: 13, fontWeight: 600, color: t.text, flex: 1,
                    minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {b.bot_name || b.bot_id}
                  </span>
                  <select
                    value={b.role}
                    onChange={(e) => updateBot.mutate({ bot_id: b.bot_id, role: e.target.value })}
                    style={{
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                      padding: "3px 8px", color: t.text, fontSize: 11, cursor: "pointer",
                      outline: "none",
                    }}
                  >
                    <option value="member">Member</option>
                    <option value="orchestrator">Orchestrator</option>
                  </select>
                </div>
                {writeProtectedPaths.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, paddingLeft: 2 }}>
                    {writeProtectedPaths.map((p) => {
                      const allowed = botWriteAccess.includes(p);
                      return (
                        <button
                          key={p}
                          onClick={() => toggleWriteAccess(p)}
                          style={{
                            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
                            padding: "2px 8px", fontSize: 10, fontFamily: "monospace",
                            borderRadius: 4, cursor: "pointer",
                            border: `1px solid ${allowed ? t.success : t.surfaceBorder}`,
                            background: allowed ? t.successSubtle : "transparent",
                            color: allowed ? t.success : t.textDim,
                          }}
                          title={allowed ? `Revoke write access to ${p}` : `Grant write access to ${p}`}
                        >
                          {allowed ? "W" : "\u2014"} {p.replace("/workspace/", "")}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}
