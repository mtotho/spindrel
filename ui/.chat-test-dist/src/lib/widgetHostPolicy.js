function normalizePresentationFamily(family, fallback = "card") {
    if (family === "chip" || family === "panel" || family === "card") {
        return family;
    }
    return fallback;
}
function resolveWrapperSurface(chrome, widgetConfig) {
    const raw = widgetConfig?.wrapper_surface;
    if (raw === "surface")
        return "surface";
    if (raw === "plain")
        return "plain";
    return chrome.borderless ? "plain" : "surface";
}
function resolveHeaderWrapperSurface(chrome, headerBackdropMode) {
    if (headerBackdropMode === "glass")
        return "translucent";
    if (headerBackdropMode === "clear")
        return "plain";
    return chrome.borderless ? "plain" : "surface";
}
function resolveTitleMode(chrome, widgetConfig, presentation, enforceHidden = false) {
    if (enforceHidden)
        return "hidden";
    const raw = widgetConfig?.show_title;
    if (raw === "hide")
        return "hidden";
    if (raw === "show") {
        return presentation?.show_panel_title && presentation?.panel_title ? "panel" : "generic";
    }
    if (chrome.hideTitles)
        return "hidden";
    return presentation?.show_panel_title && presentation?.panel_title ? "panel" : "generic";
}
export function resolveWidgetHostPolicy({ layout, chrome, widgetConfig, widgetPresentation, runtimeRail = false, forceChip = false, headerBackdropMode = "default", }) {
    const zone = layout ?? "grid";
    const headerZone = zone === "header";
    const presentationFamily = forceChip
        ? "chip"
        : normalizePresentationFamily(widgetPresentation?.presentation_family, zone === "header" ? "card" : "card");
    return {
        zone,
        presentationFamily,
        wrapperSurface: headerZone
            ? resolveHeaderWrapperSurface(chrome, headerBackdropMode)
            : resolveWrapperSurface(chrome, widgetConfig),
        titleMode: runtimeRail
            ? "hidden"
            : resolveTitleMode(chrome, widgetConfig, widgetPresentation, headerZone),
        hoverScrollbars: chrome.hoverScrollbars,
        fillHeight: zone === "header" || zone === "grid" || zone === "dock" || zone === "rail",
    };
}
