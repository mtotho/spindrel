import { useUpdateWorkspaceBot } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";
import type { WorkspaceBot } from "@/src/types/api";

export interface BotsSectionProps {
  workspaceId: string;
  bots: WorkspaceBot[];
  writeProtectedPaths: string[];
}

export function BotsSection({ workspaceId, bots, writeProtectedPaths }: BotsSectionProps) {
  const t = useThemeTokens();
  const updateBot = useUpdateWorkspaceBot(workspaceId);

  if (bots.length === 0) {
    return <div className="text-xs" style={{ color: t.textDim }}>No bots connected.</div>;
  }

  return (
    <div className="flex flex-col">
      <div className="text-xs mb-2" style={{ color: t.textDim }}>
        All bots are auto-enrolled. Orchestrators see all files; members are scoped to their directory.
      </div>

      {/* Compact table */}
      <div className="flex flex-col">
        {/* Header */}
        <div className="flex flex-row items-center gap-3 px-2 py-1.5 text-xs font-semibold"
          style={{ color: t.textDim, borderBottom: `1px solid ${t.surfaceBorder}` }}>
          <span className="flex-1 min-w-0">Bot</span>
          <span className="w-28 text-center">Role</span>
          {writeProtectedPaths.length > 0 && (
            <span className="w-24 text-center">Write Access</span>
          )}
        </div>

        {/* Rows */}
        {bots.map((b) => {
          const botWriteAccess = b.write_access || [];
          const toggleWriteAccess = (path: string) => {
            const has = botWriteAccess.includes(path);
            const next = has ? botWriteAccess.filter((p) => p !== path) : [...botWriteAccess, path];
            updateBot.mutate({ bot_id: b.bot_id, write_access: next });
          };

          return (
            <div key={b.bot_id}
              className="flex flex-row items-center gap-3 px-2 py-2"
              style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}>
              {/* Bot name */}
              <span className="flex-1 min-w-0 text-xs font-medium truncate"
                style={{ color: t.text }}>
                {b.bot_name || b.bot_id}
              </span>

              {/* Role selector */}
              <div className="w-28 flex flex-row justify-center">
                <select
                  value={b.role}
                  onChange={(e) => updateBot.mutate({ bot_id: b.bot_id, role: e.target.value })}
                  className="text-xs cursor-pointer outline-none"
                  style={{
                    background: t.inputBg,
                    border: `1px solid ${t.surfaceBorder}`,
                    borderRadius: 4,
                    padding: "2px 6px",
                    color: t.text,
                  }}
                >
                  <option value="member">Member</option>
                  <option value="orchestrator">Orchestrator</option>
                </select>
              </div>

              {/* Write access chips */}
              {writeProtectedPaths.length > 0 && (
                <div className="w-24 flex flex-row flex-wrap justify-center gap-1">
                  {writeProtectedPaths.map((p) => {
                    const allowed = botWriteAccess.includes(p);
                    const shortPath = p.replace("/workspace/", "").split("/").pop() || p;
                    return (
                      <button
                        key={p}
                        onClick={() => toggleWriteAccess(p)}
                        className="inline-flex flex-row items-center text-xs font-mono cursor-pointer"
                        style={{
                          padding: "1px 5px",
                          borderRadius: 3,
                          border: `1px solid ${allowed ? t.success : t.surfaceBorder}`,
                          background: allowed ? t.successSubtle : "transparent",
                          color: allowed ? t.success : t.textDim,
                          fontSize: 10,
                        }}
                        title={`${allowed ? "Revoke" : "Grant"} write access to ${p}`}
                      >
                        {allowed ? "W" : "\u2014"} {shortPath}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
