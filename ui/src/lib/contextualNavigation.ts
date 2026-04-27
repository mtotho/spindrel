export interface ContextualNavigationState {
  backTo: string;
  backLabel?: string;
}

export function contextualNavigationState(backTo: string, backLabel?: string): ContextualNavigationState {
  return backLabel ? { backTo, backLabel } : { backTo };
}

export function readContextualNavigationState(state: unknown): ContextualNavigationState | null {
  if (!state || typeof state !== "object") return null;
  const candidate = state as { backTo?: unknown; backLabel?: unknown };
  if (typeof candidate.backTo !== "string" || candidate.backTo.length === 0) return null;
  return {
    backTo: candidate.backTo,
    backLabel: typeof candidate.backLabel === "string" ? candidate.backLabel : undefined,
  };
}

export function sameNavigationTarget(a: string, b: string): boolean {
  return stripTrailingSlash(a) === stripTrailingSlash(b);
}

function stripTrailingSlash(value: string): string {
  return value.length > 1 ? value.replace(/\/+$/, "") : value;
}
