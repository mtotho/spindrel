import type { EdgeDescriptor } from "./edges";
import type { NodePosition } from "./layout";
import { NODE_W, NODE_H } from "./layout";

interface EdgeLayerProps {
  edges: EdgeDescriptor[];
  positions: Record<string, NodePosition>;
  selectedEdgeKey: string | null;
  onSelectEdge: (edge: EdgeDescriptor) => void;
  /** World-space bounding box; SVG must cover at least this area. */
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
}

export function edgeKey(e: EdgeDescriptor): string {
  return `${e.fromId}->${e.toId}${e.isSecondary ? "*" : ""}`;
}

function nodeCenter(pos: NodePosition) {
  return { cx: pos.x + NODE_W / 2, cy: pos.y + NODE_H / 2 };
}

function nodeBottom(pos: NodePosition) {
  return { cx: pos.x + NODE_W / 2, cy: pos.y + NODE_H };
}

function nodeTop(pos: NodePosition) {
  return { cx: pos.x + NODE_W / 2, cy: pos.y };
}

export function EdgeLayer({ edges, positions, selectedEdgeKey, onSelectEdge, bounds }: EdgeLayerProps) {
  const padding = 200;
  const width = bounds.maxX - bounds.minX + padding * 2;
  const height = bounds.maxY - bounds.minY + padding * 2;
  const offsetX = bounds.minX - padding;
  const offsetY = bounds.minY - padding;

  return (
    <svg
      data-testid="pipeline-canvas-edges"
      style={{
        position: "absolute",
        left: offsetX,
        top: offsetY,
        width,
        height,
        pointerEvents: "none",
        overflow: "visible",
      }}
    >
      {edges.map((e) => {
        const from = positions[e.fromId];
        const to = positions[e.toId];
        if (!from || !to) return null;

        const start = e.isSecondary ? nodeCenter(from) : nodeBottom(from);
        const end = e.isSecondary ? nodeCenter(to) : nodeTop(to);
        const x1 = start.cx - offsetX;
        const y1 = start.cy - offsetY;
        const x2 = end.cx - offsetX;
        const y2 = end.cy - offsetY;
        const midX = (x1 + x2) / 2;
        const midY = (y1 + y2) / 2;

        const key = edgeKey(e);
        const isSelected = selectedEdgeKey === key;
        const dashed = e.kind !== "unconditional";
        const opacity = e.isSecondary ? 0.45 : 1;
        const strokeWidth = e.isSecondary ? 1 : isSelected ? 2 : 1.5;

        const labelText = e.isSecondary
          ? null
          : e.kind === "complex"
            ? "conditional"
            : e.label;

        return (
          <g
            key={key}
            data-testid={`edge-${key}`}
            data-kind={e.kind}
            data-secondary={e.isSecondary ? "true" : "false"}
            opacity={opacity}
            style={{ pointerEvents: e.isSecondary ? "none" : "auto", cursor: "pointer" }}
            onClick={(ev) => {
              ev.stopPropagation();
              onSelectEdge(e);
            }}
          >
            {/* Hit target — wider than the visible stroke for easier clicking. */}
            {!e.isSecondary && (
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="transparent"
                strokeWidth={14}
              />
            )}
            <line
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="rgb(var(--color-surface-border))"
              strokeWidth={strokeWidth}
              strokeDasharray={dashed ? "4 4" : undefined}
              markerEnd={e.isSecondary ? undefined : "url(#pipeline-edge-arrow)"}
            />
            {labelText && (
              <foreignObject
                x={midX - 80}
                y={midY - 12}
                width={160}
                height={24}
                style={{ pointerEvents: "none" }}
              >
                <div
                  className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                    isSelected
                      ? "bg-accent/15 text-accent"
                      : "bg-surface text-text-dim"
                  }`}
                  style={{ display: "inline-block" }}
                >
                  {labelText}
                </div>
              </foreignObject>
            )}
          </g>
        );
      })}
      <defs>
        <marker
          id="pipeline-edge-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgb(var(--color-surface-border))" />
        </marker>
      </defs>
    </svg>
  );
}
