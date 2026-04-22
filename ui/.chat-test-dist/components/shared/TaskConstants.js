import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Clock, AlertCircle, CheckCircle2, Loader2, RefreshCw, XCircle, } from "lucide-react";
// ---------------------------------------------------------------------------
// Color maps — `fg` is still used by status dots and other inline-style consumers
// ---------------------------------------------------------------------------
export const TYPE_BADGE_COLORS = {
    scheduled: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6", tw: "bg-blue-500/[0.12] text-blue-600 dark:text-blue-400" },
    heartbeat: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04", tw: "bg-yellow-500/[0.12] text-yellow-700 dark:text-yellow-400" },
    memory_hygiene: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", tw: "bg-purple-500/[0.12] text-purple-700 dark:text-purple-400" },
    delegation: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", tw: "bg-purple-500/[0.12] text-purple-700 dark:text-purple-400" },
    exec: { bg: "rgba(107,114,128,0.12)", fg: "#6b7280", tw: "bg-gray-500/[0.12] text-gray-600 dark:text-gray-400" },
    callback: { bg: "rgba(239,68,68,0.12)", fg: "#dc2626", tw: "bg-red-500/[0.12] text-red-600 dark:text-red-400" },
    api: { bg: "rgba(34,197,94,0.12)", fg: "#16a34a", tw: "bg-green-500/[0.12] text-green-700 dark:text-green-400" },
    workflow: { bg: "rgba(249,115,22,0.12)", fg: "#ea580c", tw: "bg-orange-500/[0.12] text-orange-700 dark:text-orange-400" },
    agent: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af", tw: "bg-gray-500/[0.08] text-gray-500 dark:text-gray-400" },
    pipeline: { bg: "rgba(168,85,247,0.12)", fg: "#9333ea", tw: "bg-purple-500/[0.12] text-purple-700 dark:text-purple-400" },
};
export const STATUS_CFG = {
    pending: { bg: "rgba(107,114,128,0.12)", fg: "#6b7280", icon: Clock, label: "Pending", tw: "bg-gray-500/[0.12] text-gray-600 dark:text-gray-400" },
    running: { bg: "rgba(59,130,246,0.12)", fg: "#3b82f6", icon: Loader2, label: "Running", tw: "bg-blue-500/[0.12] text-blue-600 dark:text-blue-400" },
    complete: { bg: "rgba(34,197,94,0.12)", fg: "#16a34a", icon: CheckCircle2, label: "Complete", tw: "bg-green-500/[0.12] text-green-700 dark:text-green-400" },
    failed: { bg: "rgba(239,68,68,0.12)", fg: "#dc2626", icon: AlertCircle, label: "Failed", tw: "bg-red-500/[0.12] text-red-600 dark:text-red-400" },
    active: { bg: "rgba(234,179,8,0.12)", fg: "#ca8a04", icon: RefreshCw, label: "Active", tw: "bg-yellow-500/[0.12] text-yellow-700 dark:text-yellow-400" },
    upcoming: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af", icon: Clock, label: "Upcoming", tw: "bg-gray-500/[0.08] text-gray-500 dark:text-gray-400" },
    cancelled: { bg: "rgba(107,114,128,0.08)", fg: "#9ca3af", icon: XCircle, label: "Cancelled", tw: "bg-gray-500/[0.08] text-gray-500 dark:text-gray-400" },
};
export const BOT_COLORS = [
    { bg: "rgba(59,130,246,0.12)", border: "#3b82f6", dot: "#3b82f6", fg: "#2563eb" },
    { bg: "rgba(168,85,247,0.12)", border: "#a855f7", dot: "#a855f7", fg: "#9333ea" },
    { bg: "rgba(236,72,153,0.12)", border: "#ec4899", dot: "#ec4899", fg: "#db2777" },
    { bg: "rgba(239,68,68,0.12)", border: "#ef4444", dot: "#ef4444", fg: "#dc2626" },
    { bg: "rgba(249,115,22,0.12)", border: "#f97316", dot: "#f97316", fg: "#ea580c" },
    { bg: "rgba(234,179,8,0.12)", border: "#eab308", dot: "#eab308", fg: "#ca8a04" },
    { bg: "rgba(34,197,94,0.12)", border: "#22c55e", dot: "#22c55e", fg: "#16a34a" },
    { bg: "rgba(20,184,166,0.12)", border: "#14b8a6", dot: "#14b8a6", fg: "#0d9488" },
    { bg: "rgba(6,182,212,0.12)", border: "#06b6d4", dot: "#06b6d4", fg: "#0891b2" },
    { bg: "rgba(99,102,241,0.12)", border: "#6366f1", dot: "#6366f1", fg: "#4f46e5" },
    { bg: "rgba(244,63,94,0.12)", border: "#f43f5e", dot: "#f43f5e", fg: "#e11d48" },
    { bg: "rgba(132,204,22,0.12)", border: "#84cc16", dot: "#84cc16", fg: "#65a30d" },
];
export function botColor(botId) {
    let hash = 0;
    for (let i = 0; i < botId.length; i++) {
        hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
    }
    return BOT_COLORS[Math.abs(hash) % BOT_COLORS.length];
}
export function displayTitle(task) {
    if (task.title)
        return task.title;
    if (!task.prompt)
        return "(no title)";
    const clean = task.prompt.replace(/\n/g, " ").trim();
    return clean.length > 60 ? clean.substring(0, 57) + "..." : clean;
}
// ---------------------------------------------------------------------------
// Small presentational components
// ---------------------------------------------------------------------------
const TYPE_LABELS = {
    memory_hygiene: "dreaming",
};
export function TypeBadge({ type }) {
    const c = TYPE_BADGE_COLORS[type] || TYPE_BADGE_COLORS.agent;
    const label = TYPE_LABELS[type] || type;
    return (_jsx("span", { className: `inline-block px-1.5 py-px rounded text-[9px] font-semibold uppercase tracking-wider ${c.tw}`, children: label }));
}
export function TaskStatusBadge({ status }) {
    const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
    const Icon = cfg.icon;
    return (_jsxs("span", { className: `inline-flex flex-row items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold shrink-0 whitespace-nowrap ${cfg.tw}`, children: [_jsx(Icon, { size: 10 }), cfg.label] }));
}
export function BotDot({ botId, size = 8 }) {
    const c = botColor(botId);
    return (_jsx("div", { className: "rounded-full shrink-0", style: { width: size, height: size, background: c.dot } }));
}
