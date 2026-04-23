import type { WidgetPresentation } from "@/src/types/api";
import type { DashboardChrome } from "@/src/lib/dashboardGrid";

export type PresentationFamily = "card" | "chip" | "panel";
export type HostTitleMode = "hidden" | "generic" | "panel";
export type HeaderBackdropMode = "default" | "glass" | "clear";
export type WidgetLayout = "chip" | "header" | "rail" | "dock" | "grid";
export type HostSurface = "surface" | "plain" | "translucent";

export interface ResolvedWidgetHostPolicy {
  zone: WidgetLayout;
  presentationFamily: PresentationFamily;
  wrapperSurface: HostSurface;
  titleMode: HostTitleMode;
  hoverScrollbars: boolean;
  fillHeight: boolean;
}

function normalizePresentationFamily(
  family: unknown,
  fallback: PresentationFamily = "card",
): PresentationFamily {
  if (family === "chip" || family === "panel" || family === "card") {
    return family;
  }
  return fallback;
}

function resolveWrapperSurface(
  chrome: DashboardChrome,
  widgetConfig: Record<string, unknown> | null | undefined,
): HostSurface {
  const raw = widgetConfig?.wrapper_surface;
  if (raw === "surface") return "surface";
  if (raw === "plain") return "plain";
  return chrome.borderless ? "plain" : "surface";
}

function resolveHeaderWrapperSurface(
  chrome: DashboardChrome,
  headerBackdropMode: HeaderBackdropMode,
): HostSurface {
  if (headerBackdropMode === "glass") return "translucent";
  if (headerBackdropMode === "clear") return "plain";
  return chrome.borderless ? "plain" : "surface";
}

function resolveTitleMode(
  chrome: DashboardChrome,
  widgetConfig: Record<string, unknown> | null | undefined,
  presentation: WidgetPresentation | null | undefined,
  enforceHidden = false,
): HostTitleMode {
  if (enforceHidden) return "hidden";
  const raw = widgetConfig?.show_title;
  if (raw === "hide") return "hidden";
  if (raw === "show") {
    return presentation?.show_panel_title && presentation?.panel_title ? "panel" : "generic";
  }
  if (chrome.hideTitles) return "hidden";
  return presentation?.show_panel_title && presentation?.panel_title ? "panel" : "generic";
}

export function resolveWidgetHostPolicy({
  layout,
  chrome,
  widgetConfig,
  widgetPresentation,
  runtimeRail = false,
  forceChip = false,
  headerBackdropMode = "default",
}: {
  layout?: WidgetLayout;
  chrome: DashboardChrome;
  widgetConfig: Record<string, unknown> | null | undefined;
  widgetPresentation?: WidgetPresentation | null;
  runtimeRail?: boolean;
  forceChip?: boolean;
  headerBackdropMode?: HeaderBackdropMode;
}): ResolvedWidgetHostPolicy {
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
