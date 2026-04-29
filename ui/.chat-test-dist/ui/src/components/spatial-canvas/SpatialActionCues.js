import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { AlertTriangle, Clock3, History, Radio } from "lucide-react";
import { mapCueIntent, mapCueRank, mapStateLabel, mapStateMeta, mapStateTone } from "./SpatialObjectStatus.js";
const CUE_VIEWPORT_MARGIN_WORLD = 220;
const CUE_DOT_THRESHOLD = 0.35;
export function objectWorldBbox(item, margin = 0) {
    const w = item.worldW ?? 96;
    const h = item.worldH ?? 72;
    return {
        minX: item.worldX - w / 2 - margin,
        minY: item.worldY - h / 2 - margin,
        maxX: item.worldX + w / 2 + margin,
        maxY: item.worldY + h / 2 + margin,
    };
}
export function objectNearViewport(item, viewport) {
    if (!viewport)
        return false;
    const bbox = objectWorldBbox(item, CUE_VIEWPORT_MARGIN_WORLD);
    return bbox.minX < viewport.maxX && bbox.maxX > viewport.minX && bbox.minY < viewport.maxY && bbox.maxY > viewport.minY;
}
export function shouldRenderCueMarker(item) {
    return Boolean(item.workState && mapCueIntent(item.workState) !== "quiet");
}
export function shouldShowCueHalo(item, selectedObjectId, scale) {
    return shouldRenderCueMarker(item) && item.id !== selectedObjectId && scale >= CUE_DOT_THRESHOLD;
}
export function topActionCompassItems(objects, viewport, limit = 3) {
    return objects
        .filter(shouldRenderCueMarker)
        .slice()
        .sort((a, b) => {
        const aCue = cuePriority(a);
        const bCue = cuePriority(b);
        if (aCue !== bCue)
            return bCue - aCue;
        const aNear = objectNearViewport(a, viewport) ? 1 : 0;
        const bNear = objectNearViewport(b, viewport) ? 1 : 0;
        if (aNear !== bNear)
            return bNear - aNear;
        return a.distance - b.distance || a.label.localeCompare(b.label);
    })
        .slice(0, limit);
}
function cuePriority(item) {
    return mapCueRank(item.workState) * 1000 + (item.workState?.cue?.priority ?? 0);
}
function cueIcon(intent) {
    if (intent === "investigate")
        return AlertTriangle;
    if (intent === "next")
        return Clock3;
    if (intent === "recent")
        return History;
    return Radio;
}
function cueToneClass(item) {
    const tone = mapStateTone(item.workState);
    if (tone === "danger")
        return "text-danger ring-danger/55 bg-danger/[0.075]";
    if (tone === "warning")
        return "text-warning ring-warning/50 bg-warning/[0.075]";
    if (tone === "accent")
        return "text-accent ring-accent/45 bg-accent/[0.07]";
    return "text-text-muted ring-surface-border bg-surface-raised/80";
}
function cueLabel(item) {
    return mapStateLabel(item.workState) ?? "Map cue";
}
function cueTitle(item) {
    const label = cueLabel(item);
    const meta = mapStateMeta(item.workState);
    return meta ? `${label}: ${meta}` : label;
}
function kindLabel(kind) {
    if (kind === "channel")
        return "Channel";
    if (kind === "widget")
        return "Widget";
    if (kind === "bot")
        return "Bot";
    return "Landmark";
}
export function SpatialActionCueLayer({ objects, selectedObjectId, highlightedObjectId, scale, suppressedObjectIds, }) {
    const visible = objects.filter((item) => shouldRenderCueMarker(item) && !suppressedObjectIds?.has(item.id));
    if (!visible.length)
        return null;
    const inverseScale = 1 / Math.max(scale, 0.2);
    return (_jsx(_Fragment, { children: visible.map((item) => {
            const intent = mapCueIntent(item.workState);
            const Icon = cueIcon(intent);
            const showHalo = shouldShowCueHalo(item, selectedObjectId, scale);
            const highlighted = highlightedObjectId === item.id;
            const width = Math.max(42, Math.min(220, (item.worldW ?? 96) * scale + 24));
            const height = Math.max(34, Math.min(160, (item.worldH ?? 72) * scale + 24));
            const toneClass = cueToneClass(item);
            return (_jsx("div", { "data-testid": "spatial-action-cue-marker", "data-spatial-action-cue-id": item.id, "data-spatial-action-cue-intent": intent, title: cueTitle(item), className: "pointer-events-none absolute z-[4996]", style: {
                    left: item.worldX,
                    top: item.worldY,
                    transform: `translate(-50%, -50%) scale(${inverseScale})`,
                    transformOrigin: "center center",
                }, children: _jsxs("div", { className: `relative transition-transform duration-150 ${highlighted ? "scale-105" : "scale-100"}`, children: [showHalo && (_jsx("div", { "data-spatial-action-cue-halo": "true", className: `rounded-md ring-1 ring-offset-2 ring-offset-surface ${toneClass}`, style: { width, height } })), _jsxs("div", { className: `absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full ring-1 ${toneClass}`, children: [_jsx(Icon, { size: 13 }), _jsx("span", { className: "sr-only", children: cueLabel(item) })] })] }) }, `action-cue-${item.id}`));
        }) }));
}
export function ActionCompass({ objects, viewport, selectedObjectId, highlightedObjectId, onHighlight, }) {
    const items = topActionCompassItems(objects, viewport, 3);
    if (!items.length)
        return null;
    return (_jsxs("div", { "data-testid": "spatial-action-compass", className: "absolute left-4 top-4 z-[2] w-[280px] rounded-md bg-surface-raised/90 p-1.5 text-sm text-text ring-1 ring-surface-border/70", onPointerDown: (event) => event.stopPropagation(), children: [_jsx("div", { className: "px-2 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75", children: "Now" }), _jsx("div", { className: "space-y-1", children: items.map((item, index) => {
                    const intent = mapCueIntent(item.workState);
                    const Icon = cueIcon(intent);
                    const highlighted = highlightedObjectId === item.id;
                    return (_jsxs("button", { type: "button", "data-testid": "spatial-action-compass-row", "data-spatial-action-compass-id": item.id, "data-spatial-action-compass-intent": intent, className: `flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ${item.id === selectedObjectId || highlighted
                            ? "bg-accent/[0.08]"
                            : "hover:bg-surface-overlay/60 focus-visible:bg-surface-overlay/60"}`, onPointerEnter: () => onHighlight(item.id), onPointerLeave: () => onHighlight(null), onFocus: () => onHighlight(item.id), onBlur: () => onHighlight(null), onClick: () => item.onSelect(), children: [_jsx("span", { className: `flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 ${cueToneClass(item)}`, children: _jsx(Icon, { size: 12 }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate text-xs font-medium text-text", children: item.label }), _jsxs("span", { className: "block truncate text-[11px] text-text-dim", children: [cueLabel(item), " - ", kindLabel(item.kind)] })] }), _jsx("span", { className: "text-[10px] font-medium text-text-dim", children: index + 1 })] }, item.id));
                }) })] }));
}
