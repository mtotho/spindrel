import { useMemo } from "react";
import { ShieldAlert, Check, XCircle, Sparkles, Pin } from "lucide-react";
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
  const isCap = approval.tool_name === "activate_capability";
  const capability =
    (approval.dispatch_metadata as Record<string, any> | null)?._capability ?? null;

  const handle = (approved: boolean, pinCapability?: string) => {
    decide.mutate({
      approvalId: approval.id,
      data: {
        approved,
        decided_by: "user",
        ...(pinCapability ? { pin_capability: pinCapability } : {}),
      },
    });
  };

  const label = isCap && capability?.name ? capability.name : approval.tool_name;
  const description =
    isCap && capability?.description ? capability.description : approval.reason;

  return (
    <div
      className="self-start max-w-full overflow-hidden rounded-md"
      style={{
        backgroundColor: t.overlayLight,
        border: `1px solid ${t.warningBorder}`,
      }}
    >
      <div className="flex flex-row items-center gap-2 px-2.5 py-1.5">
        {isCap ? (
          <Sparkles size={12} color={t.warning} />
        ) : (
          <ShieldAlert size={12} color={t.warning} />
        )}
        <span
          className="text-xs"
          style={{
            color: isCap ? t.text : t.textMuted,
            fontWeight: isCap ? 600 : 400,
            fontFamily: isCap ? "inherit" : "'Menlo', monospace",
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
          {isCap ? (
            <span className="inline-flex items-center gap-1">
              <Check size={11} />
              Allow
            </span>
          ) : (
            "Approve"
          )}
        </button>
        {isCap && capability?.id && (
          <button
            disabled={decide.isPending}
            onClick={() => handle(true, capability.id)}
            title="Allow and permanently add to this bot's capabilities"
            className="rounded text-xs font-semibold px-3 py-1 border-0 inline-flex items-center gap-1"
            style={{
              backgroundColor: t.purple,
              color: "#fff",
              opacity: decide.isPending ? 0.6 : 1,
              cursor: decide.isPending ? "default" : "pointer",
            }}
          >
            <Pin size={11} />
            Allow & Pin
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
