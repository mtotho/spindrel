import type { ThemeTokens } from "../../theme/tokens";
import type { SharedToolTranscriptEntry } from "./toolTranscriptModel";
import { CodePreviewRenderer, CODE_FONT_STACK, TERMINAL_FONT_STACK } from "./CodePreviewRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { buildHarnessApprovalPreview } from "./harnessApprovalPreviewModel";

function EndTruncatedPath({
  value,
  color,
  fontFamily,
  fontSize,
}: {
  value: string;
  color: string;
  fontFamily?: string;
  fontSize?: number;
}) {
  return (
    <span
      className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap"
      title={value}
      style={{
        color,
        direction: "rtl",
        display: "inline-block",
        fontFamily,
        fontSize,
        textAlign: "left",
      }}
    >
      {value}
    </span>
  );
}

export function describeApprovalRequest(
  approval: NonNullable<SharedToolTranscriptEntry["approval"]>,
): { action: string; target: string | null } {
  const args = approval.arguments ?? {};
  const rawToolName = approval.toolName || "tool";
  const toolName = rawToolName.toLowerCase();
  const stringArg = (...keys: string[]): string | null => {
    for (const key of keys) {
      const value = args[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    return null;
  };

  if (toolName === "file") {
    const operation = stringArg("operation")?.toLowerCase() ?? "run";
    const target = stringArg("path", "file_path", "target_path", "destination");
    const actionByOperation: Record<string, string> = {
      overwrite: "Overwrite file",
      delete: "Delete file",
      edit: "Edit file",
      write: "Write file",
      create: "Create file",
      append: "Append file",
      move: "Move file",
      restore: "Restore file",
    };
    return {
      action: actionByOperation[operation] ?? `${operation.charAt(0).toUpperCase()}${operation.slice(1)} file`,
      target,
    };
  }

  if (rawToolName === "Bash") return { action: "Run command", target: stringArg("description", "command") };
  if (rawToolName === "Edit") return { action: "Edit file", target: stringArg("file_path", "path") };
  if (rawToolName === "Write") return { action: "Write file", target: stringArg("file_path", "path") };
  if (rawToolName === "ExitPlanMode") return { action: "Exit plan mode", target: null };

  return {
    action: `Run ${rawToolName}`,
    target: stringArg("path", "file_path", "target_path", "name", "id"),
  };
}

function HarnessToolPreview({
  toolName,
  args,
  t,
  chatMode = "default",
}: {
  toolName: string;
  args: Record<string, unknown>;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
}) {
  const isTerminalMode = chatMode === "terminal";
  const codeFont = isTerminalMode ? TERMINAL_FONT_STACK : CODE_FONT_STACK;
  const preview = buildHarnessApprovalPreview(toolName, args);
  return (
    <div
      className={isTerminalMode ? "" : "border-b px-3 py-2"}
      style={{
        borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
        backgroundColor: isTerminalMode ? "transparent" : t.overlayLight,
        padding: isTerminalMode ? "0 0 4px 0" : undefined,
      }}
    >
      <div
        className="text-[10px] font-medium uppercase mb-1"
        style={{
          color: t.textDim,
          letterSpacing: isTerminalMode ? "normal" : undefined,
          fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
        }}
      >
        {toolName}
      </div>
      {preview.kind === "bash" && (
        <div className="flex flex-col gap-1">
          {preview.description && (
            <div className="text-[11px]" style={{ color: t.textMuted }}>
              {preview.description}
            </div>
          )}
          {preview.command && (
            <pre
              className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
              style={{ fontFamily: codeFont, color: t.text }}
            >
              {preview.command.length > 800 ? `${preview.command.slice(0, 800)}...` : preview.command}
            </pre>
          )}
        </div>
      )}
      {preview.kind === "diff" && (
        <div className="flex flex-col gap-1" data-testid="harness-approval-diff-preview">
          <DiffRenderer
            body={preview.body}
            rendererVariant={isTerminalMode ? "terminal-chat" : "default-chat"}
            t={t}
          />
        </div>
      )}
      {preview.kind === "code" && (
        <div className="flex flex-col gap-1" data-testid="harness-approval-code-preview">
          {preview.target && (
            <div className="text-[11px] font-mono" style={{ color: t.textMuted }}>
              {preview.target}
            </div>
          )}
          <CodePreviewRenderer text={preview.body} target={preview.target} t={t} maxLines={40} />
        </div>
      )}
      {preview.kind === "plan" && (
        <pre
          className="m-0 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11.5px]"
          style={{ fontFamily: codeFont, color: t.text }}
        >
          {preview.body}
        </pre>
      )}
      {preview.kind === "json" && (
        <CodePreviewRenderer text={preview.body} target="args.json" t={t} maxLines={40} />
      )}
    </div>
  );
}

export function HarnessAwareApprovalRow({
  approval,
  onApproval,
  decidingIds,
  t,
  chatMode = "default",
}: {
  approval: NonNullable<SharedToolTranscriptEntry["approval"]>;
  onApproval: (approvalId: string, approved: boolean, options?: { bypassRestOfTurn?: boolean }) => void;
  decidingIds?: Set<string>;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
}) {
  const isHarness = approval.toolType === "harness";
  const isTerminalMode = chatMode === "terminal";
  const busy = !!decidingIds?.has(approval.approvalId);
  const summary = describeApprovalRequest(approval);
  return (
    <div
      className={isTerminalMode ? "overflow-hidden" : "rounded-lg border overflow-hidden"}
      style={{
        borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
        backgroundColor: isTerminalMode ? "transparent" : t.surfaceRaised,
        marginLeft: isTerminalMode ? 18 : undefined,
        marginTop: isTerminalMode ? 2 : undefined,
        fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
      }}
    >
      {isHarness && approval.toolName && (
        <HarnessToolPreview
          toolName={approval.toolName}
          args={approval.arguments ?? {}}
          t={t}
          chatMode={chatMode}
        />
      )}
      <div className="flex items-center gap-2 flex-wrap" style={{ padding: isTerminalMode ? "2px 0 0 0" : "10px 12px" }}>
        <div className="min-w-0" style={{ flex: "1 1 220px" }}>
          <div className="flex items-baseline gap-1.5 min-w-0" style={{ color: t.text }}>
            <span
              className="text-[12px] font-semibold"
              style={{ fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}
            >
              {summary.action}
            </span>
            {summary.target && (
              <EndTruncatedPath
                value={summary.target}
                color={t.textMuted}
                fontFamily={isTerminalMode ? TERMINAL_FONT_STACK : CODE_FONT_STACK}
                fontSize={11}
              />
            )}
          </div>
          <div className="text-[11px] mt-0.5" style={{ color: t.textMuted }}>
            {approval.reason || "Tool policy requires approval before execution"}
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => onApproval(approval.approvalId, true)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
          style={{
            border: isTerminalMode ? `1px solid ${t.successBorder}` : "none",
            cursor: busy ? "default" : "pointer",
            backgroundColor: isTerminalMode ? "transparent" : t.success,
            color: isTerminalMode ? t.success : "#fff",
            opacity: busy ? 0.6 : 1,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          {busy ? "Working..." : "Approve"}
        </button>
        {isHarness && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onApproval(approval.approvalId, true, { bypassRestOfTurn: true })}
            className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
            style={{
              border: `1px solid ${t.successBorder}`,
              cursor: busy ? "default" : "pointer",
              backgroundColor: "transparent",
              color: t.success,
              opacity: busy ? 0.6 : 1,
              fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
            }}
            title="Approve this call AND auto-approve every remaining tool call in this turn. Reverts at end of turn."
          >
            {isTerminalMode ? "Approve turn" : "Approve all this turn"}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => onApproval(approval.approvalId, false)}
          className={isTerminalMode ? "text-[11px] font-semibold px-1 py-0" : "text-[12px] font-semibold px-3 py-1 rounded"}
          style={{
            border: isTerminalMode ? `1px solid ${t.dangerBorder}` : "none",
            cursor: busy ? "default" : "pointer",
            backgroundColor: isTerminalMode ? "transparent" : t.danger,
            color: isTerminalMode ? t.danger : "#fff",
            opacity: busy ? 0.6 : 1,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
          }}
        >
          Deny
        </button>
      </div>
    </div>
  );
}
