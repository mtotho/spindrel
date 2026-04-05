import { useState } from "react";
import { Bot, ChevronRight, ChevronDown } from "lucide-react";
import type { ThemeTokens } from "../../theme/tokens";

interface Delegation {
  bot_id?: string;
  prompt_preview?: string;
  notify_parent?: boolean;
}

interface Props {
  delegations: Delegation[];
  t: ThemeTokens;
}

/**
 * Compact expandable card rendered on parent messages that delegated.
 * Visual language follows ToolBadges (pill shape, chevron expand, monospace font).
 */
export function DelegationCard({ delegations, t }: Props) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (delegations.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {delegations.map((d, idx) => {
          const hasPreview = !!d.prompt_preview;
          const isExpanded = expandedIdx === idx;
          return (
            <div key={idx} style={{ display: "flex", flexDirection: "column" }}>
              <div
                onClick={hasPreview ? () => setExpandedIdx(isExpanded ? null : idx) : undefined}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  paddingLeft: 6,
                  paddingRight: 8,
                  paddingTop: 3,
                  paddingBottom: 3,
                  borderRadius: 4,
                  backgroundColor: isExpanded ? "rgba(139, 92, 246, 0.15)" : "rgba(139, 92, 246, 0.08)",
                  border: "1px solid rgba(139, 92, 246, 0.25)",
                  cursor: hasPreview ? "pointer" : "default",
                  transition: "background-color 0.15s",
                }}
              >
                <Bot size={10} color="#8b5cf6" />
                <span style={{ fontSize: 11, color: "#8b5cf6", fontFamily: "'Menlo', monospace" }}>
                  Delegated to {d.bot_id || "agent"}
                </span>
                {hasPreview && (
                  isExpanded
                    ? <ChevronDown size={10} color="#8b5cf6" />
                    : <ChevronRight size={10} color="#8b5cf6" />
                )}
              </div>
            </div>
          );
        })}
      </div>
      {expandedIdx !== null && delegations[expandedIdx]?.prompt_preview && (
        <div
          style={{
            borderRadius: 6,
            backgroundColor: "rgba(139, 92, 246, 0.06)",
            border: "1px solid rgba(139, 92, 246, 0.15)",
            padding: "6px 10px",
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          <pre
            style={{
              margin: 0,
              fontSize: 11,
              fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
              color: t.textMuted,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              lineHeight: "1.4",
            }}
          >
            {delegations[expandedIdx].prompt_preview}
          </pre>
          {delegations[expandedIdx].notify_parent === false && (
            <div style={{ fontSize: 10, color: t.textDim, marginTop: 4, fontStyle: "italic" }}>
              fire-and-forget (no callback)
            </div>
          )}
        </div>
      )}
    </div>
  );
}
