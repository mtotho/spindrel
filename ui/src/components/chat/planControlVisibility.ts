import type { ComposerPlanMode } from "./planControl";

export type PlanModeControlVisibility = "auto" | "show" | "hide";

export interface ComposerPlanControlVisibilityInput {
  canTogglePlanMode: boolean;
  planMode: ComposerPlanMode;
  planModeControl?: PlanModeControlVisibility | null;
  harnessRuntime?: string | null;
}

function isActivePlanMode(planMode: ComposerPlanMode): boolean {
  return planMode === "planning"
    || planMode === "executing"
    || planMode === "blocked"
    || planMode === "done";
}

export function shouldShowComposerPlanControl({
  canTogglePlanMode,
  planMode,
  planModeControl = "auto",
  harnessRuntime = null,
}: ComposerPlanControlVisibilityInput): boolean {
  if (!canTogglePlanMode) return false;
  if (isActivePlanMode(planMode)) return true;
  if (planModeControl === "show") return true;
  if (planModeControl === "hide") return false;
  return !!harnessRuntime;
}
