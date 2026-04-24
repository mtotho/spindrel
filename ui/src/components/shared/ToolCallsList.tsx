import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TurnToolCall } from "@/src/api/hooks/useTurns";
import { formatDuration } from "@/src/utils/time";

export interface ToolCallsListProps {
  toolCalls: TurnToolCall[];
  isWide?: boolean;
}

export function ToolCallsList({ toolCalls, isWide }: ToolCallsListProps) {
  const [expanded, setExpanded] = useState(false);
  if (toolCalls.length === 0) return null;

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded(!expanded);
        }}
        className="inline-flex items-center gap-1 rounded-full bg-purple/10 px-2 py-0.5 text-[11px] font-medium text-purple transition-colors hover:bg-purple/15"
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {toolCalls.length} tool call{toolCalls.length !== 1 ? "s" : ""}
      </button>
      {expanded && (
        <div className="mt-1 flex flex-col gap-1 pl-2">
          {toolCalls.map((tc, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 rounded-md bg-surface-raised/40 px-2 py-1 text-[11px] text-text-muted ${isWide ? "flex-nowrap" : "flex-wrap"}`}
            >
              <span className="shrink-0 font-semibold text-text">{tc.tool_name}</span>
              <span className="shrink-0 text-[10px] text-text-dim">{tc.tool_type}</span>
              {tc.duration_ms != null && (
                <span className="shrink-0 text-text-dim">{formatDuration(tc.duration_ms)}</span>
              )}
              {tc.error && (
                <span className="shrink-0 rounded-full bg-danger/10 px-1.5 py-px text-[10px] font-semibold text-danger">
                  ERR
                </span>
              )}
              {isWide && tc.arguments_preview && (
                <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-text-dim">
                  {tc.arguments_preview}
                </span>
              )}
              {isWide && tc.result_preview && (
                <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-text-muted">
                  {tc.result_preview}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
