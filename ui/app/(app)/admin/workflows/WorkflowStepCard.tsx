/**
 * Compact step card for the workflow step list (left pane).
 * Shows step number, ID, type badge, one-line preview, and indicator dots.
 */

import { type ThemeTokens } from "@/src/theme/tokens";
import {
  Zap, Terminal, Bot, ShieldAlert, GitBranch, RotateCcw,
  ArrowUp, ArrowDown, X,
} from "lucide-react";
import type { WorkflowStep } from "@/src/types/api";

// Step type color mapping
const STEP_TYPE_COLORS = {
  agent: (t: ThemeTokens) => ({ border: t.accent, bg: t.accentSubtle, text: t.accent, icon: Bot }),
  tool: (t: ThemeTokens) => ({ border: t.purple, bg: t.purpleSubtle, text: t.purple, icon: Zap }),
  exec: (t: ThemeTokens) => ({ border: t.warning, bg: t.warningSubtle, text: t.warning, icon: Terminal }),
} as const;

function getStepTypeStyle(type: string | undefined, t: ThemeTokens) {
  return (STEP_TYPE_COLORS[type as keyof typeof STEP_TYPE_COLORS] || STEP_TYPE_COLORS.agent)(t);
}

interface WorkflowStepCardProps {
  step: WorkflowStep;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  selected: boolean;
  onSelect: () => void;
  onMove?: (dir: -1 | 1) => void;
  onRemove?: () => void;
  disabled?: boolean;
  t: ThemeTokens;
}

export function WorkflowStepCard({
  step, index, isFirst, isLast, selected, onSelect,
  onMove, onRemove, disabled, t,
}: WorkflowStepCardProps) {
  const stepType = step.type || "agent";
  const typeStyle = getStepTypeStyle(stepType, t);
  const Icon = typeStyle.icon;

  // One-line preview
  const preview = stepType === "tool"
    ? step.tool_name || ""
    : step.prompt
      ? (stepType === "exec" ? "$ " : "") + step.prompt.split("\n")[0].slice(0, 60)
      : "";

  // Indicator dots
  const hasCondition = step.when && Object.keys(step.when).length > 0;
  const hasApproval = step.requires_approval;
  const hasRetry = step.on_failure?.startsWith("retry:");

  return (
    <button type="button"
      onClick={onSelect}
      style={{
        borderRadius: 8,
        borderWidth: 1,
        borderColor: selected ? typeStyle.border : t.surfaceBorder,
        backgroundColor: selected ? typeStyle.bg : t.codeBg,
        borderLeftWidth: 3,
        borderLeftColor: typeStyle.border,
        overflow: "hidden",
      }}
    >
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
        padding: "8px 10px",
        cursor: "pointer", userSelect: "none",
      }}>
        {/* Step number */}
        <span style={{
          width: 20, height: 20, borderRadius: 10, flexShrink: 0,
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
          background: typeStyle.bg, border: `1px solid ${typeStyle.border}`,
          fontSize: 10, fontWeight: 700, color: typeStyle.text,
        }}>
          {index + 1}
        </span>

        {/* Step ID + preview */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: t.text,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {step.id}
          </div>
          {preview && (
            <div style={{
              fontSize: 11, color: t.textDim, marginTop: 1,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {preview}
            </div>
          )}
        </div>

        {/* Type badge */}
        <span style={{
          fontSize: 10, padding: "1px 5px", borderRadius: 3, flexShrink: 0,
          display: "inline-flex", alignItems: "center", gap: 3,
          background: typeStyle.bg, border: `1px solid ${typeStyle.border}`,
          color: typeStyle.text, whiteSpace: "nowrap",
        }}>
          <Icon size={10} />
          {stepType}
        </span>

        {/* Indicator dots */}
        <div style={{ display: "flex", flexDirection: "row", gap: 3, flexShrink: 0 }}>
          {hasCondition && (
            <span title="Conditional" style={{ display: "flex" }}>
              <GitBranch size={11} color={t.purple} />
            </span>
          )}
          {hasApproval && (
            <span title="Requires approval" style={{ display: "flex", flexDirection: "row" }}>
              <ShieldAlert size={11} color={t.warning} />
            </span>
          )}
          {hasRetry && (
            <span title={step.on_failure || "Retry"} style={{ display: "flex", flexDirection: "row" }}>
              <RotateCcw size={11} color={t.textMuted} />
            </span>
          )}
        </div>

        {/* Reorder + delete buttons */}
        {!disabled && onMove && onRemove && (
          <div
            style={{ display: "flex", flexDirection: "row", gap: 1, flexShrink: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => onMove(-1)}
              disabled={isFirst}
              style={{
                background: "none", border: "none", padding: 3, borderRadius: 3,
                cursor: isFirst ? "default" : "pointer", opacity: isFirst ? 0.2 : 0.6,
                display: "flex", flexDirection: "row", alignItems: "center",
              }}
            >
              <ArrowUp size={11} color={t.textDim} />
            </button>
            <button
              onClick={() => onMove(1)}
              disabled={isLast}
              style={{
                background: "none", border: "none", padding: 3, borderRadius: 3,
                cursor: isLast ? "default" : "pointer", opacity: isLast ? 0.2 : 0.6,
                display: "flex", flexDirection: "row", alignItems: "center",
              }}
            >
              <ArrowDown size={11} color={t.textDim} />
            </button>
            <button
              onClick={() => onRemove()}
              style={{
                background: "none", border: "none", padding: 3, borderRadius: 3,
                cursor: "pointer", opacity: 0.6,
                display: "flex", flexDirection: "row", alignItems: "center",
              }}
            >
              <X size={11} color={t.danger} />
            </button>
          </div>
        )}
      </div>
    </button>
  );
}
