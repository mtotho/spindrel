import type { WidgetPresentation } from "@/src/types/api";
import type { DashboardChrome } from "@/src/lib/dashboardGrid";
import type { HostSurface, WidgetLayout } from "@/src/components/chat/renderers/InteractiveHtmlRenderer";

export type PresentationFamily = "card" | "chip" | "panel";
export type HostTitleMode = "hidden" | "generic" | "panel";

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

function resolveTitleMode(
  chrome: DashboardChrome,
  widgetConfig: Record<string, unknown> | null | undefined,
  presentation: WidgetPresentation | null | undefined,
): HostTitleMode {
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
}: {
  layout?: WidgetLayout;
  chrome: DashboardChrome;
  widgetConfig: Record<string, unknown> | null | undefined;
  widgetPresentation?: WidgetPresentation | null;
  runtimeRail?: boolean;
  forceChip?: boolean;
}): ResolvedWidgetHostPolicy {
  const zone = layout ?? "grid";
  const presentationFamily = forceChip
    ? "chip"
    : normalizePresentationFamily(widgetPresentation?.presentation_family, zone === "header" ? "card" : "card");
  return {
    zone,
    presentationFamily,
    wrapperSurface: resolveWrapperSurface(chrome, widgetConfig),
    titleMode: runtimeRail ? "hidden" : resolveTitleMode(chrome, widgetConfig, widgetPresentation),
    hoverScrollbars: chrome.hoverScrollbars,
    fillHeight: zone === "header" || zone === "grid" || zone === "dock" || zone === "rail",
  };
}
