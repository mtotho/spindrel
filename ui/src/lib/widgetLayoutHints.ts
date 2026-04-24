import type { ChatZone, WidgetLayoutHints, WidgetPresentation } from "@/src/types/api";

export interface WidgetLayoutBounds {
  minW: number;
  minH: number;
  maxW: number;
  maxH?: number;
}

function positiveCell(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : null;
}

function baseBoundsForZone(zone: ChatZone, cols: number): WidgetLayoutBounds {
  switch (zone) {
    case "rail":
    case "dock":
      return { minW: 1, minH: 1, maxW: 1 };
    case "header":
      return { minW: 1, minH: 1, maxW: Math.max(1, cols), maxH: 2 };
    case "grid":
    default:
      return { minW: 1, minH: 1, maxW: Math.max(1, cols) };
  }
}

function clampBounds(
  base: WidgetLayoutBounds,
  hints: WidgetLayoutHints | null | undefined,
): WidgetLayoutBounds {
  const minW = positiveCell(hints?.min_cells?.w);
  const minH = positiveCell(hints?.min_cells?.h);
  const maxW = positiveCell(hints?.max_cells?.w);
  const maxH = positiveCell(hints?.max_cells?.h);

  let nextMinW = Math.max(base.minW, minW ?? base.minW);
  let nextMinH = Math.max(base.minH, minH ?? base.minH);
  let nextMaxW = Math.min(base.maxW, maxW ?? base.maxW);
  let nextMaxH =
    base.maxH == null
      ? maxH ?? undefined
      : Math.min(base.maxH, maxH ?? base.maxH);

  if (nextMaxW < nextMinW) nextMaxW = nextMinW;
  if (nextMaxH != null && nextMaxH < nextMinH) nextMaxH = nextMinH;

  return {
    minW: nextMinW,
    minH: nextMinH,
    maxW: nextMaxW,
    maxH: nextMaxH,
  };
}

export function getWidgetLayoutBounds(
  presentation: WidgetPresentation | null | undefined,
  zone: ChatZone,
  cols: number,
): WidgetLayoutBounds {
  return baseBoundsForZone(zone, cols);
}

export function getSuggestedWidgetSize(
  presentation: WidgetPresentation | null | undefined,
  zone: ChatZone,
  fallback: { w: number; h: number },
  cols: number,
): { w: number; h: number } {
  const preferredZone = presentation?.layout_hints?.preferred_zone?.trim();
  const resolvedPreferredZone = preferredZone === "chip" ? "header" : preferredZone;
  const base =
    zone === "header" && preferredZone === "chip"
      ? { w: 4, h: 1 }
      : fallback;
  const bounds =
    resolvedPreferredZone === zone
      ? clampBounds(baseBoundsForZone(zone, cols), presentation?.layout_hints)
      : baseBoundsForZone(zone, cols);
  const width = Math.max(bounds.minW, Math.min(bounds.maxW, Math.max(1, base.w)));
  const maxHeight = bounds.maxH;
  const height = Math.max(
    bounds.minH,
    maxHeight == null
      ? Math.max(1, base.h)
      : Math.min(maxHeight, Math.max(1, base.h)),
  );
  return { w: width, h: height };
}
