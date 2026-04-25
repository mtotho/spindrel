import { useCallback } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { AlertTriangle } from "lucide-react";
import type { StepDef } from "@/src/api/hooks/useTasks";
import { stepMeta, isKnownStepType } from "../TaskStepEditorModel";
import { NODE_W, NODE_H } from "./layout";

interface StepNodeProps {
  step: StepDef;
  x: number;
  y: number;
  selected: boolean;
  stale: boolean;
  onPointerDown: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onSelect: () => void;
}

export function StepNode({
  step,
  x,
  y,
  selected,
  stale,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onSelect,
}: StepNodeProps) {
  const meta = stepMeta(step.type);
  const Icon = meta.icon;
  const known = isKnownStepType(step.type);

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect();
  }, [onSelect]);

  return (
    <div
      data-testid={`step-node-${step.id}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={handleClick}
      className={`absolute rounded-md flex flex-col gap-1 px-3 py-2 select-none cursor-grab active:cursor-grabbing transition-colors ${
        selected
          ? "bg-surface-overlay ring-2 ring-accent/60"
          : "bg-surface-raised hover:bg-surface-overlay/80 ring-1 ring-surface-border"
      }`}
      style={{
        left: x,
        top: y,
        width: NODE_W,
        minHeight: NODE_H,
        touchAction: "none",
      }}
    >
      <div className="flex flex-row items-center gap-1.5">
        <span
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${
            known ? meta.bgBadge : "bg-surface-overlay text-text-dim"
          }`}
        >
          <Icon size={10} />
          {meta.label}
        </span>
        {stale && (
          <span
            className="inline-flex items-center gap-1 text-warning-muted"
            title="Condition references a step that now runs after this one or no longer exists. Edit in the JSON tab to fix."
          >
            <AlertTriangle size={11} />
          </span>
        )}
      </div>
      <div className="text-xs font-medium text-text truncate">
        {step.label || step.id}
      </div>
      {step.id !== (step.label ?? "") && (
        <div className="text-[10px] text-text-dim font-mono truncate">{step.id}</div>
      )}
    </div>
  );
}
