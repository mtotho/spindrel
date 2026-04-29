export const HARNESS_APPROVAL_MODE_CYCLE = [
    "bypassPermissions",
    "acceptEdits",
    "default",
    "plan",
];
const HARNESS_APPROVAL_MODE_LABEL = {
    bypassPermissions: "bypass",
    acceptEdits: "edits",
    default: "ask",
    plan: "read-only",
};
const HARNESS_APPROVAL_MODE_DESCRIPTION = {
    bypassPermissions: "Bypass: every tool call is auto-approved.",
    acceptEdits: "Accept edits: Edit and Write are auto-approved; Bash and others ask.",
    default: "Ask: write and exec tools require approval.",
    plan: "Read-only permissions: write and exec tools are blocked until the harness exits native plan mode.",
};
const HARNESS_APPROVAL_MODE_TONE = {
    bypassPermissions: "success",
    acceptEdits: "warning",
    default: "neutral",
    plan: "plan",
};
export function normalizeHarnessApprovalMode(mode) {
    return HARNESS_APPROVAL_MODE_CYCLE.includes(mode)
        ? mode
        : "bypassPermissions";
}
export function getNextHarnessApprovalMode(mode) {
    const normalized = normalizeHarnessApprovalMode(mode);
    const idx = HARNESS_APPROVAL_MODE_CYCLE.indexOf(normalized);
    return HARNESS_APPROVAL_MODE_CYCLE[(idx + 1) % HARNESS_APPROVAL_MODE_CYCLE.length];
}
export function getHarnessApprovalModeControlState(mode) {
    const normalized = normalizeHarnessApprovalMode(mode);
    const description = HARNESS_APPROVAL_MODE_DESCRIPTION[normalized];
    return {
        mode: normalized,
        label: HARNESS_APPROVAL_MODE_LABEL[normalized],
        title: `Harness permission mode: ${description} Click to cycle.`,
        tone: HARNESS_APPROVAL_MODE_TONE[normalized],
    };
}
