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
}: {
  channelId: string;
  liveApprovalIds: ReadonlySet<string>;
}) {
  const t = useThemeTokens();
  const { data } = useChannelPendingApprovals(channelId);

  const orphans = useMemo(
    () => (data ?? []).filter((a) => !liveApprovalIds.has(a.id)),
    [data, liveApprovalIds],
  );

  if (orphans.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 px-5 py-2">
      {orphans.map((a) => (
        <OrphanApprovalCard key={a.id} approval={a} t={t} />
      ))}
    </div>
  );
}

function OrphanApprovalCard({
  approval,
  t,
}: {
  approval: ToolApproval;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const decide = useDecideApproval();
  const isHarness = approval.tool_type === "harness";

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
      className="self-start max-w-full overflow-hidden rounded-md"
      style={{
        backgroundColor: t.overlayLight,
        border: `1px solid ${t.warningBorder}`,
      }}
    >
      <div className="flex flex-row items-center gap-2 px-2.5 py-1.5">
        <ShieldAlert size={12} color={t.warning} />
        <span
          className="text-xs"
          style={{
            color: t.textMuted,
            fontWeight: 400,
            fontFamily: "'Menlo', monospace",
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
          className="px-2.5 pb-1.5 text-[11px] leading-[1.3]"
          style={{ color: t.textMuted }}
        >
          {description}
        </div>
      )}
      {argsPreview && (
        <pre
          className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words px-2.5 pb-2 text-[11px]"
          style={{ fontFamily: "'Menlo', monospace", color: t.text }}
        >
          {argsPreview}
        </pre>
      )}
      <div
        className="flex flex-row flex-wrap items-center gap-2 px-2.5 py-2"
        style={{ borderTop: `1px solid ${t.warningBorder}` }}
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
          className="rounded text-xs font-semibold px-3 py-1 border-0"
          style={{
            backgroundColor: t.success,
            color: "#fff",
            opacity: decide.isPending ? 0.6 : 1,
            cursor: decide.isPending ? "default" : "pointer",
          }}
        >
          Approve
        </button>
        {isHarness && (
          <button
            disabled={decide.isPending}
            onClick={() => handle(true, true)}
            className="rounded text-xs font-semibold px-3 py-1 inline-flex items-center gap-1"
            style={{
              backgroundColor: "transparent",
              color: t.success,
              border: `1px solid ${t.successBorder}`,
              opacity: decide.isPending ? 0.6 : 1,
              cursor: decide.isPending ? "default" : "pointer",
            }}
            title="Approve this call AND auto-approve every remaining tool call in this turn."
          >
            Approve all this turn
          </button>
        )}
        <button
          disabled={decide.isPending}
          onClick={() => handle(false)}
          className="rounded text-xs font-semibold px-3 py-1 border-0 inline-flex items-center gap-1"
          style={{
            backgroundColor: t.danger,
            color: "#fff",
            opacity: decide.isPending ? 0.6 : 1,
            cursor: decide.isPending ? "default" : "pointer",
          }}
        >
          <XCircle size={11} />
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
