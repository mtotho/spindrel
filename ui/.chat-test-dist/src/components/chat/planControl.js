export function getComposerPlanControlState({ planMode, hasPlan, canApprovePlan = false, }) {
    switch (planMode) {
        case "planning":
            return {
                label: "Planning",
                title: "Plan mode: Planning",
                tone: "warning",
                active: true,
                showMenu: true,
                primaryActionLabel: "Exit plan",
                canApprove: canApprovePlan,
            };
        case "executing":
            return {
                label: "Executing",
                title: "Plan mode: Executing",
                tone: "warning",
                active: true,
                showMenu: true,
                primaryActionLabel: "Exit plan",
                canApprove: false,
            };
        case "blocked":
            return {
                label: "Blocked",
                title: "Plan mode: Blocked",
                tone: "danger",
                active: true,
                showMenu: true,
                primaryActionLabel: "Exit plan",
                canApprove: false,
            };
        case "done":
            return {
                label: "Done",
                title: "Plan mode: Done",
                tone: "success",
                active: true,
                showMenu: true,
                primaryActionLabel: "Exit plan",
                canApprove: false,
            };
        case "chat":
        case null:
        case undefined:
        default:
            return {
                label: hasPlan ? "Resume plan" : "Start plan",
                title: hasPlan ? "Resume plan mode" : "Start plan mode",
                tone: "neutral",
                active: false,
                showMenu: false,
                primaryActionLabel: hasPlan ? "Resume plan" : "Start plan",
                canApprove: false,
            };
    }
}
