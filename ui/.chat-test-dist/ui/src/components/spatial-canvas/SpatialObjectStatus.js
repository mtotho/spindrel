import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle, Clock, History, Play, Radio } from "lucide-react";
export function mapCueIntent(state) {
    return state?.cue?.intent ?? (state?.status === "error" || state?.status === "warning" ? "investigate"
        : state?.status === "running" || state?.status === "scheduled" || state?.status === "active" ? "next"
            : state?.status === "recent" ? "recent"
                : "quiet");
}
export function mapStateLabel(state) {
    if (!state)
        return null;
    if (state.cue?.label)
        return state.cue.label;
    if (state.status === "error")
        return state.primary_signal || "Error";
    if (state.status === "warning")
        return state.primary_signal || "Warning";
    if (state.status === "running")
        return state.primary_signal || "Running";
    if (state.status === "scheduled")
        return state.next?.title || state.primary_signal || "Scheduled";
    if (state.status === "recent")
        return state.primary_signal || "Recent";
    return null;
}
export function mapStateMeta(state) {
    if (!state)
        return null;
    if (state.cue?.reason && state.cue.intent !== "quiet")
        return state.cue.reason;
    const parts = [];
    if (state.counts.upcoming > 0)
        parts.push(`${state.counts.upcoming} next`);
    if (state.counts.recent > 0)
        parts.push(`${state.counts.recent} recent`);
    if (state.counts.warnings > 0)
        parts.push(`${state.counts.warnings} warning${state.counts.warnings === 1 ? "" : "s"}`);
    return parts.join(" · ") || null;
}
export function mapStateTone(state) {
    if (!state)
        return "muted";
    const intent = mapCueIntent(state);
    if (intent === "investigate") {
        return state.severity === "warning" ? "warning" : "danger";
    }
    if (intent === "next")
        return "accent";
    if (state.status === "error" || state.severity === "critical" || state.severity === "error")
        return "danger";
    if (state.status === "warning" || state.severity === "warning")
        return "warning";
    if (state.status === "running" || state.status === "scheduled" || state.status === "active")
        return "accent";
    return "muted";
}
export function mapCueRank(state) {
    const intent = mapCueIntent(state);
    if (intent === "investigate")
        return 3;
    if (intent === "next")
        return 2;
    if (intent === "recent")
        return 1;
    return 0;
}
export function statusRingClass(state) {
    const tone = mapStateTone(state);
    if (tone === "danger")
        return "ring-2 ring-danger/80";
    if (tone === "warning")
        return "ring-2 ring-warning/70";
    if (tone === "accent")
        return "ring-2 ring-accent/45";
    return "";
}
export function ObjectStatusPill({ state, compact = false, iconOnly = false, }) {
    if (mapCueIntent(state) === "quiet")
        return null;
    const label = mapStateLabel(state);
    if (!state || !label)
        return null;
    const tone = mapStateTone(state);
    const Icon = mapCueIntent(state) === "investigate" || tone === "danger" || tone === "warning"
        ? AlertTriangle
        : state.status === "running"
            ? Play
            : state.status === "scheduled"
                ? Clock
                : state.status === "recent"
                    ? History
                    : Radio;
    const cls = tone === "danger"
        ? "bg-danger/10 text-danger"
        : tone === "warning"
            ? "bg-warning/10 text-warning"
            : tone === "accent"
                ? "bg-accent/10 text-accent"
                : "bg-surface-overlay text-text-muted";
    return (_jsxs("span", { className: `inline-flex min-w-0 max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`, title: label, children: [_jsx(Icon, { size: compact ? 9 : 10, className: "shrink-0" }), iconOnly ? _jsx("span", { className: "sr-only", children: label }) : _jsx("span", { className: "truncate", children: label })] }));
}
