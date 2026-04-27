import { useMemo } from "react";
import { ShieldAlert, XCircle } from "lucide-react";
import {
  useChannelPendingApprovals,
  useDecideApproval,
  type ToolApproval,
} from "@/src/api/hooks/useApprovals";
import { useThemeTokens } from "@/src/theme/tokens";

/**
 * Inline approvals whose originating turn is no longer in memory
 * (page refresh, background task, mobile tab-wake reconnect, etc.).
 * Dedupes against approval ids already represented in live turn cards —
 * `StreamingIndicator` renders those itself via `SingleToolCallCard`.
 */
export function ChannelPendingApprovals({
  channelId,
  liveApprovalIds,
  chatMode = "default",
}: {
  channelId: string;
  liveApprovalIds: ReadonlySet<string>;
  chatMode?: "default" | "terminal";
}) {
  const t = useThemeTokens();
  const isTerminalMode = chatMode === "terminal";
  const { data } = useChannelPendingApprovals(channelId);

  const orphans = useMemo(
    () => (data ?? []).filter((a) => !liveApprovalIds.has(a.id)),
    [data, liveApprovalIds],
  );

  if (orphans.length === 0) return null;

  return (
    <div
      className="flex flex-col"
      style={{
        gap: isTerminalMode ? 6 : 8,
        padding: isTerminalMode ? "4px 0 6px 0" : "8px 20px",
      }}
    >
      {orphans.map((a) => (
        <OrphanApprovalCard key={a.id} approval={a} t={t} chatMode={chatMode} />
      ))}
    </div>
  );
}

function OrphanApprovalCard({
  approval,
  t,
  chatMode = "default",
}: {
  approval: ToolApproval;
  t: ReturnType<typeof useThemeTokens>;
  chatMode?: "default" | "terminal";
}) {
  const decide = useDecideApproval();
  const isHarness = approval.tool_type === "harness";
  const isTerminalMode = chatMode === "terminal";
  const terminalFont = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

  const handle = (approved: boolean, bypassRestOfTurn = false) => {
    decide.mutate({
      approvalId: approval.id,
      data: {
        approved,
        decided_by: "user",
        ...(bypassRestOfTurn ? { bypass_rest_of_turn: true } : {}),
      },
    });
  };

  const label = approval.tool_name;
  const description = approval.reason;
  const argsPreview = isHarness ? buildHarnessOrphanPreview(approval) : null;

  return (
    <div
      className={isTerminalMode ? "self-start max-w-full overflow-hidden" : "self-start max-w-full overflow-hidden rounded-md"}
      style={{
        backgroundColor: isTerminalMode ? "transparent" : t.overlayLight,
        border: isTerminalMode ? "none" : `1px solid ${t.warningBorder}`,
        fontFamily: isTerminalMode ? terminalFont : undefined,
        marginLeft: isTerminalMode ? 18 : undefined,
      }}
    >
      <div
        className="flex flex-row items-center gap-2"
        style={{ padding: isTerminalMode ? "0 0 2px 0" : "6px 10px" }}
      >
        {isTerminalMode ? (
          <span style={{ color: t.warning, fontSize: 11 }}>?</span>
        ) : (
          <ShieldAlert size={12} color={t.warning} />
        )}
        <span
          className="text-xs"
          style={{
            color: t.textMuted,
            fontWeight: 400,
            fontFamily: isTerminalMode ? terminalFont : "'Menlo', monospace",
          }}
        >
          {label}
        </span>
        <span className="text-[11px] font-medium" style={{ color: t.warning }}>
          Waiting for approval…
        </span>
      </div>
      {description && (
        <div
          className="text-[11px] leading-[1.3]"
          style={{ color: t.textMuted, padding: isTerminalMode ? "0 0 2px 18px" : "0 10px 6px" }}
        >
          {description}
        </div>
      )}
      {argsPreview && (
        <pre
          className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11px]"
          style={{
            fontFamily: isTerminalMode ? terminalFont : "'Menlo', monospace",
            color: t.text,
            padding: isTerminalMode ? "0 0 4px 18px" : "0 10px 8px",
          }}
        >
          {argsPreview}
        </pre>
      )}
      <div
        className="flex flex-row flex-wrap items-center gap-2"
        style={{
          borderTop: isTerminalMode ? "none" : `1px solid ${t.warningBorder}`,
          padding: isTerminalMode ? "0 0 0 18px" : "8px 10px",
        }}
      >
        <span
          className="flex-1 min-w-[100px] text-[11px]"
          style={{ color: t.textDim }}
        >
          {approval.bot_id}
        </span>
        <button
          disabled={decide.isPending}
          onClick={() => handle(true)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "rounded text-xs font-semibold px-3 py-1 border-0"}
          style={{
            backgroundColor: isTerminalMode ? "transparent" : t.success,
            color: isTerminalMode ? t.success : "#fff",
            border: isTerminalMode ? `1px solid ${t.successBorder}` : "none",
            opacity: decide.isPending ? 0.6 : 1,
            cursor: decide.isPending ? "default" : "pointer",
            fontFamily: isTerminalMode ? terminalFont : undefined,
          }}
        >
          Approve
        </button>
        {isHarness && (
          <button
            disabled={decide.isPending}
            onClick={() => handle(true, true)}
            className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0 inline-flex items-center gap-1" : "rounded text-xs font-semibold px-3 py-1 inline-flex items-center gap-1"}
            style={{
              backgroundColor: "transparent",
              color: t.success,
              border: `1px solid ${t.successBorder}`,
              opacity: decide.isPending ? 0.6 : 1,
              cursor: decide.isPending ? "default" : "pointer",
              fontFamily: isTerminalMode ? terminalFont : undefined,
            }}
            title="Approve this call AND auto-approve every remaining tool call in this turn."
          >
            {isTerminalMode ? "Approve turn" : "Approve all this turn"}
          </button>
        )}
        <button
          disabled={decide.isPending}
          onClick={() => handle(false)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0 border-0 inline-flex items-center gap-1" : "rounded text-xs font-semibold px-3 py-1 border-0 inline-flex items-center gap-1"}
          style={{
            backgroundColor: isTerminalMode ? "transparent" : t.danger,
            color: isTerminalMode ? t.danger : "#fff",
            border: isTerminalMode ? `1px solid ${t.dangerBorder}` : "none",
            opacity: decide.isPending ? 0.6 : 1,
            cursor: decide.isPending ? "default" : "pointer",
            fontFamily: isTerminalMode ? terminalFont : undefined,
          }}
        >
          {!isTerminalMode && <XCircle size={11} />}
          Deny
        </button>
      </div>
    </div>
  );
}

function buildHarnessOrphanPreview(approval: ToolApproval): string | null {
  const args = (approval.arguments ?? {}) as Record<string, unknown>;
  const str = (key: string): string | null => {
    const v = args[key];
    return typeof v === "string" && v.trim() ? v : null;
  };
  if (approval.tool_name === "Bash") {
    const cmd = str("command");
    if (cmd) return cmd.length > 600 ? `${cmd.slice(0, 600)}…` : cmd;
  } else if (approval.tool_name === "Edit") {
    const file = str("file_path") ?? str("path") ?? "";
    const oldS = str("old_string") ?? "";
    const newS = str("new_string") ?? "";
    return [file, oldS && `- ${oldS}`, newS && `+ ${newS}`].filter(Boolean).join("\n");
  } else if (approval.tool_name === "Write") {
    const file = str("file_path") ?? str("path") ?? "";
    const content = str("content") ?? "";
    const lines = content.split(/\r?\n/).slice(0, 20);
    return [file, lines.join("\n")].filter(Boolean).join("\n");
  } else if (approval.tool_name === "ExitPlanMode") {
    return str("plan");
  }
  if (Object.keys(args).length === 0) return null;
  return JSON.stringify(args, null, 2);
}
