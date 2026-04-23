export interface HeaderContextBudget {
  utilization: number;
  consumed: number;
  total: number;
  gross?: number;
  current?: number;
  cached?: number;
  contextProfile?: string;
}

export interface HeaderSessionStats {
  utilization: number | null;
  consumedTokens?: number | null;
  totalTokens: number | null;
  grossPromptTokens: number | null;
  currentPromptTokens: number | null;
  cachedPromptTokens: number | null;
  completionTokens: number | null;
  contextProfile: string | null;
  turnsInContext: number | null;
  turnsUntilCompaction: number | null;
}

export interface ResolvedHeaderMetrics {
  utilization: number | null;
  total: number | null;
  gross: number | null;
  current: number | null;
  cached: number | null;
  completion: number | null;
  contextProfile: string | null;
  turnsInContext: number | null;
  turnsUntilCompaction: number | null;
  hasTokenMetrics: boolean;
  hasAnyTokenUsage: boolean;
}

export function resolveHeaderMetrics(
  contextBudget?: HeaderContextBudget | null,
  sessionHeaderStats?: HeaderSessionStats | null,
): ResolvedHeaderMetrics {
  const total = contextBudget?.total ?? sessionHeaderStats?.totalTokens ?? null;
  const gross = contextBudget?.gross
    ?? sessionHeaderStats?.grossPromptTokens
    ?? sessionHeaderStats?.consumedTokens
    ?? contextBudget?.consumed
    ?? null;
  const current = contextBudget?.current ?? sessionHeaderStats?.currentPromptTokens ?? gross;
  const hasAnyTokenUsage = typeof gross === "number" || typeof current === "number" || typeof total === "number";

  return {
    utilization: contextBudget?.utilization ?? sessionHeaderStats?.utilization ?? null,
    total,
    gross,
    current,
    cached: contextBudget?.cached ?? sessionHeaderStats?.cachedPromptTokens ?? null,
    completion: sessionHeaderStats?.completionTokens ?? null,
    contextProfile: contextBudget?.contextProfile ?? sessionHeaderStats?.contextProfile ?? null,
    turnsInContext: sessionHeaderStats?.turnsInContext ?? null,
    turnsUntilCompaction: sessionHeaderStats?.turnsUntilCompaction ?? null,
    hasTokenMetrics: typeof total === "number" && total > 0 && typeof gross === "number" && gross >= 0,
    hasAnyTokenUsage,
  };
}

export interface RouteSessionChrome {
  modeLabel: "Primary" | "Session";
  inlineTitle: string | null;
  inlineMeta: string | null;
  subtitleIdentity: string | null;
}

function compactSessionTitle(raw?: string | null): string | null {
  const trimmed = raw?.trim().replace(/\s+/g, " ") || null;
  if (!trimmed) return null;
  if (trimmed.length <= 56) return trimmed;
  return `${trimmed.slice(0, 53).trimEnd()}...`;
}

export function resolveRouteSessionChrome(
  isSessionRoute: boolean,
  sessionTitle?: string | null,
  lastActiveLabel?: string | null,
): RouteSessionChrome {
  const trimmedTitle = compactSessionTitle(sessionTitle);
  const trimmedMeta = lastActiveLabel?.trim() || null;
  if (!isSessionRoute) {
    return {
      modeLabel: "Primary",
      inlineTitle: null,
      inlineMeta: null,
      subtitleIdentity: null,
    };
  }
  return {
    modeLabel: "Session",
    inlineTitle: trimmedTitle,
    inlineMeta: trimmedMeta,
    subtitleIdentity: trimmedTitle || trimmedMeta ? null : "session",
  };
}
