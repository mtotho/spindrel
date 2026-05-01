import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { AlertTriangle, ChevronRight, Clock3, ExternalLink, History, ListChecks, Minimize2, Radio } from "lucide-react";
import { useEffect, useState } from "react";
import { attentionDeckHref } from "../../lib/hubRoutes";
import { mapCueIntent, mapCueRank, mapStateLabel, mapStateMeta, mapStateTone } from "./SpatialObjectStatus.js";
const CUE_VIEWPORT_MARGIN_WORLD = 220;
const ACTION_COMPASS_MINIMIZED_KEY = "spatial.actionCompass.minimized";
function loadActionCompassMinimized() {
    if (typeof window === "undefined")
        return false;
    try {
        return window.localStorage.getItem(ACTION_COMPASS_MINIMIZED_KEY) === "1";
    }
    catch {
        return false;
    }
}
function storeActionCompassMinimized(value) {
    if (typeof window === "undefined")
        return;
    try {
        window.localStorage.setItem(ACTION_COMPASS_MINIMIZED_KEY, value ? "1" : "0");
    }
    catch {
        // Ignore storage failures; the control should still work for this session.
    }
}
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
        return "text-danger ring-danger/35 bg-surface-raised/95";
    if (tone === "warning")
        return "text-warning ring-warning/35 bg-surface-raised/95";
    if (tone === "accent")
        return "text-accent ring-accent/30 bg-surface-raised/95";
    return "text-text-muted ring-surface-border/70 bg-surface-raised/90";
}
function cueLabel(item) {
    return mapStateLabel(item.workState) ?? "Map cue";
}
function cueTitle(item) {
    const label = cueLabel(item);
    const meta = mapStateMeta(item.workState);
    return meta ? `${label}: ${meta}` : label;
}
function cueReason(item) {
    return mapStateMeta(item.workState) ?? item.workState?.cue?.reason ?? kindLabel(item.kind);
}
function cueCountLabel(item) {
    const intent = mapCueIntent(item.workState);
    const counts = item.workState?.counts;
    if (!counts)
        return null;
    if (intent === "investigate" && counts.warnings > 0)
        return `${counts.warnings}`;
    if (intent === "next" && counts.upcoming > 0)
        return `${counts.upcoming}`;
    if (intent === "recent" && counts.recent > 0)
        return `${counts.recent}`;
    return null;
}
function actionCount(objects) {
    return objects.filter(shouldRenderCueMarker).length;
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
            const highlighted = highlightedObjectId === item.id;
            const width = Math.max(42, Math.min(220, (item.worldW ?? 96) * scale + 24));
            const height = Math.max(34, Math.min(160, (item.worldH ?? 72) * scale + 24));
            const toneClass = cueToneClass(item);
            const badgeX = Math.round(width / 2 - 10);
            const badgeY = Math.round(-height / 2 + 2);
            return (_jsx("div", { "data-testid": "spatial-action-cue-marker", "data-spatial-action-cue-id": item.id, "data-spatial-action-cue-intent": intent, className: "pointer-events-none absolute z-[4996]", style: {
                    left: item.worldX,
                    top: item.worldY,
                    transform: `translate(-50%, -50%) scale(${inverseScale})`,
                    transformOrigin: "center center",
                }, children: _jsx("div", { className: `relative transition-transform duration-150 ${highlighted ? "scale-110" : "scale-100"}`, style: { width: 0, height: 0 }, children: _jsxs("button", { type: "button", title: cueTitle(item), "aria-label": `${cueLabel(item)}: ${item.label}`, className: `pointer-events-auto absolute flex h-5 min-w-5 items-center justify-center rounded-full px-1 ring-1 backdrop-blur-sm transition-transform duration-150 hover:bg-surface-overlay focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 ${toneClass} ${highlighted ? "scale-110 ring-accent/45" : ""}`, style: { transform: `translate(${badgeX}px, ${badgeY}px)` }, onPointerDown: (event) => event.stopPropagation(), onClick: (event) => {
                            event.stopPropagation();
                            item.onSelect();
                        }, children: [_jsx(Icon, { size: 13 }), _jsx("span", { className: "sr-only", children: cueLabel(item) })] }) }) }, `action-cue-${item.id}`));
        }) }));
}
export function ActionCompass({ objects, viewport, selectedObjectId, highlightedObjectId, onHighlight, collapsed = false, }) {
    const [userMinimized, setUserMinimized] = useState(loadActionCompassMinimized);
    const selectedItem = selectedObjectId
        ? objects.find((item) => item.id === selectedObjectId && shouldRenderCueMarker(item)) ?? null
        : null;
    const rankedItems = topActionCompassItems(objects, viewport, selectedItem ? 6 : 3);
    const items = selectedItem
        ? [selectedItem, ...rankedItems.filter((item) => item.id !== selectedItem.id)].slice(0, 3)
        : rankedItems.slice(0, 3);
    useEffect(() => {
        storeActionCompassMinimized(userMinimized);
    }, [userMinimized]);
    if (!items.length)
        return null;
    const total = actionCount(objects);
    const reviewAllHref = attentionDeckHref({ mode: "review" });
    const compact = collapsed || userMinimized;
    if (compact) {
        const topItem = items[0];
        const intent = mapCueIntent(topItem.workState);
        const Icon = cueIcon(intent);
        return (_jsxs("div", { "data-testid": "spatial-action-compass", "data-spatial-action-compass-collapsed": "true", "data-spatial-action-compass-user-minimized": userMinimized ? "true" : "false", className: "absolute left-4 top-4 z-[2] flex items-center gap-1 rounded-md bg-surface-raised/90 p-1 text-text ring-1 ring-surface-border/70", onPointerDown: (event) => event.stopPropagation(), children: [_jsxs("button", { type: "button", title: userMinimized ? `Show next actions: ${total}` : `Next actions: ${total}`, "aria-label": userMinimized ? `Show next actions: ${total}` : `Next actions: ${total}`, className: "flex h-9 items-center gap-2 rounded-md px-2 text-text-muted hover:bg-surface-overlay/60 hover:text-text", onPointerEnter: () => onHighlight(topItem.id), onPointerLeave: () => onHighlight(null), onFocus: () => onHighlight(topItem.id), onBlur: () => onHighlight(null), onClick: () => {
                        if (userMinimized) {
                            setUserMinimized(false);
                            return;
                        }
                        topItem.onSelect();
                    }, children: [_jsx(ListChecks, { size: 17 }), _jsx("span", { className: "rounded-full bg-surface-overlay/65 px-1.5 py-0.5 text-[10px] font-medium text-text-muted", children: total })] }), _jsx("a", { href: reviewAllHref, title: "Review all next actions", "aria-label": "Review all next actions", className: "flex h-8 w-8 items-center justify-center rounded-md text-accent hover:bg-accent/[0.08]", children: _jsx(ExternalLink, { size: 13 }) }), _jsx("button", { type: "button", title: `${cueLabel(topItem)}: ${topItem.label}`, "aria-label": `${cueLabel(topItem)}: ${topItem.label}`, className: `flex h-8 w-8 items-center justify-center rounded-full ring-1 ${cueToneClass(topItem)}`, onPointerEnter: () => onHighlight(topItem.id), onPointerLeave: () => onHighlight(null), onFocus: () => onHighlight(topItem.id), onBlur: () => onHighlight(null), onClick: () => topItem.onSelect(), children: _jsx(Icon, { size: 13 }) })] }));
    }
    return (_jsxs("div", { "data-testid": "spatial-action-compass", className: "absolute left-4 top-4 z-[2] w-[304px] rounded-md bg-surface-raised/90 p-2 text-sm text-text ring-1 ring-surface-border/70", onPointerDown: (event) => event.stopPropagation(), children: [_jsxs("div", { className: "flex items-start justify-between gap-3 px-1 pb-2", children: [_jsxs("div", { children: [_jsx("div", { className: "text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75", children: "Next actions" }), _jsx("div", { className: "mt-0.5 text-xs text-text-muted", children: "Best targets from the map." })] }), _jsxs("div", { className: "flex shrink-0 items-center gap-1", children: [_jsx("span", { className: "rounded-full bg-surface-overlay/60 px-2 py-0.5 text-[11px] text-text-dim", children: total }), _jsxs("a", { href: reviewAllHref, title: "Review all next actions", className: "flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-accent hover:bg-accent/[0.08]", children: [_jsx(ExternalLink, { size: 12 }), "Review all"] }), _jsx("button", { type: "button", title: "Minimize next actions", "aria-label": "Minimize next actions", className: "flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay/60 hover:text-text", onClick: () => setUserMinimized(true), children: _jsx(Minimize2, { size: 13 }) })] })] }), _jsx("div", { className: "space-y-1", children: items.map((item, index) => {
                    const intent = mapCueIntent(item.workState);
                    const Icon = cueIcon(intent);
                    const highlighted = highlightedObjectId === item.id;
                    const selected = item.id === selectedObjectId;
                    const count = cueCountLabel(item);
                    return (_jsxs("button", { type: "button", "data-testid": "spatial-action-compass-row", "data-spatial-action-compass-id": item.id, "data-spatial-action-compass-intent": intent, "data-spatial-action-compass-selected": selected ? "true" : "false", className: `flex w-full items-center gap-2 rounded-md text-left transition-colors duration-100 ${selected || highlighted
                            ? "bg-accent/[0.08] ring-1 ring-accent/15"
                            : index === 0
                                ? "bg-surface-overlay/35 hover:bg-surface-overlay/60 focus-visible:bg-surface-overlay/60"
                                : "hover:bg-surface-overlay/50 focus-visible:bg-surface-overlay/50"} ${index === 0 ? "px-2.5 py-2" : "px-2 py-1.5"}`, onPointerEnter: () => onHighlight(item.id), onPointerLeave: () => onHighlight(null), onFocus: () => onHighlight(item.id), onBlur: () => onHighlight(null), onClick: () => item.onSelect(), children: [_jsx("span", { className: `flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 ${cueToneClass(item)}`, children: _jsx(Icon, { size: 12 }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsxs("span", { className: "flex min-w-0 items-center gap-1.5", children: [_jsx("span", { className: "truncate text-xs font-medium text-text", children: item.label }), _jsx("span", { className: "shrink-0 rounded-full bg-surface-overlay/50 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em] text-text-dim", children: kindLabel(item.kind) })] }), _jsxs("span", { className: "mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-text-dim", children: [_jsx("span", { className: "shrink-0 font-medium text-text-muted", children: cueLabel(item) }), _jsx("span", { className: "min-w-0 truncate", children: cueReason(item) })] })] }), _jsxs("span", { className: "flex shrink-0 items-center gap-1.5", children: [count && (_jsx("span", { className: "rounded-full bg-surface-overlay/65 px-1.5 py-0.5 text-[10px] font-medium text-text-muted", children: count })), _jsx(ChevronRight, { size: 13, className: "text-text-dim" }), _jsx("span", { className: "text-[10px] font-medium text-text-dim", children: index + 1 })] })] }, item.id));
                }) })] }));
}
