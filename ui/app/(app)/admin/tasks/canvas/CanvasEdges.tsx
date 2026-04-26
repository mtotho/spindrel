import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";

interface SpindrelEdgeData extends Record<string, unknown> {
  kind?: "unconditional" | "simple" | "complex";
  badge?: string;
  isSecondary?: boolean;
  rawWhen?: Record<string, any>;
}

function badgeClasses(kind: SpindrelEdgeData["kind"]): string {
  switch (kind) {
    case "complex":
      return "bg-warning-muted/15 text-warning-muted border border-warning-muted/30";
    case "simple":
      return "bg-accent/10 text-accent border border-accent/20";
    default:
      return "bg-surface-overlay text-text-dim border border-surface-border";
  }
}

/** Sequential primary edge — solid curved bezier. */
function SequentialEdgeImpl(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd } = props;
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <BaseEdge
      path={path}
      markerEnd={markerEnd}
      style={{ stroke: "rgb(var(--color-text-dim) / 0.55)", strokeWidth: 2 }}
    />
  );
}
export const SequentialEdge = memo(SequentialEdgeImpl);

/** Anchor edge from TaskNode to first step — slightly faded. */
function AnchorEdgeImpl(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd } = props;
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <BaseEdge
      path={path}
      markerEnd={markerEnd}
      style={{ stroke: "rgb(var(--color-text-dim) / 0.3)", strokeWidth: 1.5, strokeDasharray: "3 5" }}
    />
  );
}
export const AnchorEdge = memo(AnchorEdgeImpl);

/** Conditional edge — dashed with a small badge label. */
function ConditionalEdgeImpl(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, data } = props;
  const d = (data ?? {}) as SpindrelEdgeData;
  const [path, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: d.kind === "complex" ? "rgb(var(--color-warning-muted) / 0.7)" : "rgb(var(--color-accent) / 0.65)",
          strokeWidth: 2,
          strokeDasharray: "6 4",
        }}
      />
      {d.badge && (
        <EdgeLabelRenderer>
          <div
            className={`absolute pointer-events-auto px-1.5 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap ${badgeClasses(d.kind)}`}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
            title={d.rawWhen ? JSON.stringify(d.rawWhen) : undefined}
          >
            {d.badge}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
export const ConditionalEdge = memo(ConditionalEdgeImpl);

/** Secondary "reads from" edge — faint dotted, with a small label. */
function SecondaryEdgeImpl(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, data } = props;
  const d = (data ?? {}) as SpindrelEdgeData;
  const [path, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });
  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: "rgb(var(--color-text-dim) / 0.4)",
          strokeWidth: 1.25,
          strokeDasharray: "1 4",
        }}
      />
      {d.badge && (
        <EdgeLabelRenderer>
          <div
            className="absolute pointer-events-none px-1.5 py-0.5 rounded text-[9.5px] font-medium whitespace-nowrap bg-surface-raised/70 text-text-dim border border-surface-border/60 backdrop-blur"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {d.badge}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
export const SecondaryEdge = memo(SecondaryEdgeImpl);
