/**
 * ToolTraceStrip — compact horizontal "tape" of tool calls for turns with
 * many tool uses. Each tick is one call; green for success, red for error.
 * Hover a tick for the tool name + introspection target; click the strip
 * to expand into the full vertical badge list.
 */

import type { ThemeTokens } from "../../theme/tokens";
import type { ToolResultEnvelope } from "../../types/api";
import { ChevronRight } from "lucide-react";

export type TraceTick = {
  toolName: string;
  target?: string | null;
  isError: boolean;
};

export function ToolTraceStrip({
  ticks,
  onExpand,
  t,
  chatMode = "default",
}: {
  ticks: TraceTick[];
  onExpand: () => void;
  t: ThemeTokens;
  chatMode?: "default" | "terminal";
}) {
  if (ticks.length === 0) return null;
  const total = ticks.length;
  const errors = ticks.filter((x) => x.isError).length;
  const isTerminalMode = chatMode === "terminal";

  return (
    <div
      data-testid="tool-trace-strip"
      role="button"
      tabIndex={0}
      aria-label={`${total} tool call${total === 1 ? "" : "s"}, click to expand`}
      onClick={onExpand}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onExpand();
        }
      }}
      className="inline-flex items-center gap-2 self-start mt-1.5 cursor-pointer rounded-md border px-2 py-1 transition-colors duration-150 outline-none focus-visible:ring-1"
      style={{
        backgroundColor: isTerminalMode ? "transparent" : t.surfaceRaised,
        borderColor: isTerminalMode ? "transparent" : t.surfaceBorder,
        fontFamily: isTerminalMode ? "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace" : undefined,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.textDim; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = isTerminalMode ? "transparent" : t.surfaceBorder; }}
    >
      <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: t.textDim }}>
        {total} {total === 1 ? "tool call" : "tool calls"}
        {errors > 0 && (
          <span style={{ color: t.dangerMuted, marginLeft: 4 }}>
            · {errors} err
          </span>
        )}
      </span>
      <span className="inline-flex items-end gap-[2px]" style={{ paddingTop: 2 }}>
        {ticks.map((tick, i) => {
          const label = tick.target
            ? `${tick.toolName} \u2192 ${tick.target}`
            : tick.toolName;
          return (
            <span
              key={i}
              title={label}
              aria-hidden="true"
              style={{
                display: "inline-block",
                width: 3,
                height: 10,
                borderRadius: 1,
                backgroundColor: tick.isError ? t.danger : t.success,
                opacity: tick.isError ? 0.9 : 0.7,
              }}
            />
          );
        })}
      </span>
      <ChevronRight size={11} style={{ color: t.textDim }} />
    </div>
  );
}
