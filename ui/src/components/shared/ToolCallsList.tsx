import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TurnToolCall } from "@/src/api/hooks/useTurns";
import { useThemeTokens } from "@/src/theme/tokens";
import { formatDuration } from "@/src/utils/time";

export interface ToolCallsListProps {
  toolCalls: TurnToolCall[];
  isWide?: boolean;
}

export function ToolCallsList({ toolCalls, isWide }: ToolCallsListProps) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  if (toolCalls.length === 0) return null;

  return (
    <div style={{ marginTop: 6 }}>
      <button
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: t.purpleSubtle, border: "none", borderRadius: 4,
          padding: "3px 8px", fontSize: 11, color: t.purple, cursor: "pointer",
        }}
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {toolCalls.length} tool call{toolCalls.length !== 1 ? "s" : ""}
      </button>
      {expanded && (
        <div style={{
          marginTop: 4, paddingLeft: 8,
          borderLeft: `2px solid ${t.purpleBorder}`,
        }}>
          {toolCalls.map((tc, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              padding: "3px 0", fontSize: 11, color: t.textMuted,
              flexWrap: isWide ? "nowrap" : "wrap",
            }}>
              <span style={{ fontWeight: 600, color: t.text, flexShrink: 0 }}>{tc.tool_name}</span>
              <span style={{ color: t.textDim, fontSize: 10, flexShrink: 0 }}>{tc.tool_type}</span>
              {tc.duration_ms != null && (
                <span style={{ color: t.textDim, flexShrink: 0 }}>{formatDuration(tc.duration_ms)}</span>
              )}
              {tc.error && (
                <span style={{
                  fontSize: 10, fontWeight: 600, color: t.danger,
                  background: t.dangerSubtle, padding: "1px 5px", borderRadius: 3,
                  flexShrink: 0,
                }}>ERR</span>
              )}
              {isWide && tc.arguments_preview && (
                <span style={{
                  fontSize: 10, color: t.textDim, fontFamily: "monospace",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  flex: "1 1 0", minWidth: 0,
                }}>{tc.arguments_preview}</span>
              )}
              {isWide && tc.result_preview && (
                <span style={{
                  fontSize: 10, color: t.textMuted, fontFamily: "monospace",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  flex: "1 1 0", minWidth: 0,
                }}>{tc.result_preview}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
