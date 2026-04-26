import type { Edge } from "@xyflow/react";
import type { StepDef } from "@/src/api/hooks/useTasks";

export type EdgeKind = "unconditional" | "simple" | "complex";

interface EdgeData extends Record<string, unknown> {
  kind: EdgeKind;
  badge?: string;
  rawWhen?: Record<string, any>;
  isSecondary?: boolean;
}

const SIMPLE_KEYS = new Set(["step", "status", "output_contains", "output_not_contains"]);

/**
 * Classify a `when` clause for visual rendering.
 *
 * - unconditional: when missing/empty
 * - simple:        only {step, status?, output_contains?, output_not_contains?}
 * - complex:       any all/any/not/param keys, or unrecognized keys
 */
export function classifyWhen(when: Record<string, any> | null | undefined): EdgeKind {
  if (!when || Object.keys(when).length === 0) return "unconditional";
  for (const k of Object.keys(when)) {
    if (!SIMPLE_KEYS.has(k)) return "complex";
  }
  return "simple";
}

function badgeForSimple(when: Record<string, any>): string | undefined {
  if (when.status) return `if ${when.status}`;
  if (when.output_contains) return `if contains "${truncate(when.output_contains)}"`;
  if (when.output_not_contains) return `unless contains "${truncate(when.output_not_contains)}"`;
  return undefined;
}

function truncate(s: string, n = 16): string {
  if (typeof s !== "string") return String(s);
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

const TASK_NODE_ID = "__task__";

/**
 * Build xyflow edges from a step list.
 *
 * - Primary edge from steps[idx-1] → steps[idx] (always sequential).
 * - Edge between TaskNode and the first step (for visual completeness).
 * - Secondary dotted edge from `when.step` referent if it's not the immediate
 *   predecessor (the data-dependency reference).
 */
export function buildEdges(steps: StepDef[]): Edge<EdgeData>[] {
  const edges: Edge<EdgeData>[] = [];
  if (steps.length === 0) return edges;

  // Anchor: TaskNode → first step
  edges.push({
    id: `e-task-${steps[0].id}`,
    source: TASK_NODE_ID,
    target: steps[0].id,
    type: "anchor",
    data: { kind: "unconditional" },
  });

  for (let i = 1; i < steps.length; i += 1) {
    const prev = steps[i - 1];
    const cur = steps[i];
    const kind = classifyWhen(cur.when ?? undefined);
    const badge =
      kind === "simple"
        ? badgeForSimple(cur.when as Record<string, any>)
        : kind === "complex"
          ? "conditional"
          : undefined;
    edges.push({
      id: `e-${prev.id}-${cur.id}`,
      source: prev.id,
      target: cur.id,
      type: kind === "unconditional" ? "sequential" : "conditional",
      data: { kind, badge, rawWhen: cur.when ?? undefined },
    });
  }

  // Secondary edges from non-immediate when.step references
  const idToIndex = new Map(steps.map((s, i) => [s.id, i]));
  for (let i = 0; i < steps.length; i += 1) {
    const cur = steps[i];
    const ref = cur.when?.step as string | undefined;
    if (!ref) continue;
    const refIdx = idToIndex.get(ref);
    if (refIdx === undefined) continue;
    if (refIdx === i - 1) continue; // immediate predecessor — already drawn as primary
    if (refIdx >= i) continue; // forward reference — caller surfaces a warning, edge skipped
    edges.push({
      id: `e2-${ref}-${cur.id}`,
      source: ref,
      target: cur.id,
      type: "secondary",
      data: { kind: "simple", isSecondary: true, badge: "reads from" },
    });
  }

  return edges;
}

export const TASK_NODE_ID_CONST = TASK_NODE_ID;
