function isActivePlanMode(planMode) {
    return planMode === "planning"
        || planMode === "executing"
        || planMode === "blocked"
        || planMode === "done";
}
export function shouldShowComposerPlanControl({ canTogglePlanMode, planMode, planModeControl = "auto", harnessRuntime = null, }) {
    if (!canTogglePlanMode)
        return false;
    if (isActivePlanMode(planMode))
        return true;
    if (planModeControl === "show")
        return true;
    if (planModeControl === "hide")
        return false;
    return !!harnessRuntime;
}
