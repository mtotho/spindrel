/**
 * Pipeline Canvas edge classification.
 *
 * The runtime executes `steps[]` in array order. Primary edges always reflect
 * sequential execution flow. Secondary edges visualize a `when.step` reference
 * to a non-immediate predecessor (data dependency, not execution order).
 *
 * Condition vocabulary supported by `app/services/step_executor.evaluate_condition`:
 *   {step, status?, output_contains?, output_not_contains?}
 *   {param, equals?}
 *   {all: [...]} | {any: [...]} | {not: ...}
 *
 * The Visual / Canvas tabs only render the simple step-check shapes. Anything
 * with `all` / `any` / `not` / `param` (or unrecognized keys) is "complex" —
 * shown as a neutral conditional edge with a read-only summary, never re-shaped.
 */
import type { StepDef } from "@/src/api/hooks/useTasks";

export type EdgeKind = "unconditional" | "simple" | "complex";

export interface EdgeDescriptor {
  /** Source step id (the step the edge originates from). */
  fromId: string;
  /** Target step id (the step the edge terminates at — owns `when`). */
  toId: string;
  kind: EdgeKind;
  /** Human-readable label for simple conditions; null for unconditional/complex. */
  label: string | null;
  /** Raw condition object, present for `simple` and `complex`. */
  when: Record<string, any> | null;
  /** True when this edge is the secondary (faint) condition-reference edge,
   *  drawn from a non-immediate predecessor referenced by `when.step`. */
  isSecondary: boolean;
}

const SIMPLE_KEYS = new Set(["step", "status", "output_contains", "output_not_contains"]);

export function classifyWhen(when: Record<string, any> | null | undefined): EdgeKind {
  if (!when || Object.keys(when).length === 0) return "unconditional";
  const keys = Object.keys(when);
  for (const key of keys) {
    if (!SIMPLE_KEYS.has(key)) return "complex";
  }
  return "simple";
}

export function describeWhen(when: Record<string, any> | null | undefined): string | null {
  if (!when) return null;
  const kind = classifyWhen(when);
  if (kind !== "simple") return null;
  if (typeof when.output_contains === "string") {
    return `if contains "${when.output_contains}"`;
  }
  if (typeof when.output_not_contains === "string") {
    return `if NOT contains "${when.output_not_contains}"`;
  }
  if (typeof when.status === "string") {
    return `if status = ${when.status}`;
  }
  return null;
}

/**
 * Build the edge list for a pipeline.
 *
 * - Primary edge: `steps[i-1] -> steps[i]` for i >= 1 (always sequential).
 * - Secondary edge: when `steps[i].when?.step` points at a step that is NOT
 *   the immediate predecessor, draw a faint edge from that referenced step.
 */
export function buildEdges(steps: StepDef[]): EdgeDescriptor[] {
  const edges: EdgeDescriptor[] = [];
  const idIndex = new Map<string, number>();
  steps.forEach((s, i) => idIndex.set(s.id, i));

  for (let i = 1; i < steps.length; i++) {
    const step = steps[i];
    const prev = steps[i - 1];
    const when = (step.when ?? null) as Record<string, any> | null;
    const kind = classifyWhen(when);
    edges.push({
      fromId: prev.id,
      toId: step.id,
      kind,
      label: describeWhen(when),
      when,
      isSecondary: false,
    });

    // Secondary: when.step references a non-immediate predecessor.
    const refId = when && typeof when.step === "string" ? when.step : null;
    if (refId && refId !== prev.id) {
      const refIdx = idIndex.get(refId);
      if (refIdx !== undefined && refIdx < i) {
        edges.push({
          fromId: refId,
          toId: step.id,
          kind,
          label: null,
          when,
          isSecondary: true,
        });
      }
    }
  }
  return edges;
}

/**
 * Walk steps and return ids whose `when.step` reference is now stale —
 * either points forward (target index >= current index) or to a missing step.
 * Used by the Config Panel to surface a warning chip after reorder.
 */
export function staleWhenStepRefs(steps: StepDef[]): Set<string> {
  const idIndex = new Map<string, number>();
  steps.forEach((s, i) => idIndex.set(s.id, i));
  const stale = new Set<string>();
  steps.forEach((step, i) => {
    const ref = step.when && typeof (step.when as any).step === "string"
      ? (step.when as any).step as string
      : null;
    if (!ref) return;
    const targetIdx = idIndex.get(ref);
    if (targetIdx === undefined || targetIdx >= i) stale.add(step.id);
  });
  return stale;
}
