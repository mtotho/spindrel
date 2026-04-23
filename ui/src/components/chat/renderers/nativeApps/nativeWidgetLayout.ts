export type NativeWidgetSurface = "chip" | "header" | "rail" | "dock" | "grid" | undefined;

export type NativeWidgetLayoutMode = "compact" | "standard" | "tall" | "wide";

export interface NativeWidgetLayoutProfile {
  layout: NativeWidgetSurface;
  width: number;
  height: number;
  mode: NativeWidgetLayoutMode;
  compact: boolean;
  standard: boolean;
  tall: boolean;
  wide: boolean;
}

interface NativeWidgetLayoutOptions {
  compactLayouts?: Exclude<NativeWidgetSurface, undefined>[];
  compactMaxWidth?: number;
  compactMaxHeight?: number;
  wideMinWidth?: number;
  wideMinHeight?: number;
  tallMinHeight?: number;
}

export function deriveNativeWidgetLayoutProfile(
  layout: NativeWidgetSurface,
  gridDimensions: { width: number; height: number } | undefined,
  options: NativeWidgetLayoutOptions = {},
): NativeWidgetLayoutProfile {
  const width = gridDimensions?.width ?? 0;
  const height = gridDimensions?.height ?? 0;
  const compactLayouts = options.compactLayouts ?? ["chip", "header", "rail"];
  const compactMaxWidth = options.compactMaxWidth ?? 340;
  const compactMaxHeight = options.compactMaxHeight ?? 170;
  const wideMinWidth = options.wideMinWidth ?? 560;
  const wideMinHeight = options.wideMinHeight ?? 180;
  const tallMinHeight = options.tallMinHeight ?? 260;

  let mode: NativeWidgetLayoutMode = "standard";
  if (layout && compactLayouts.includes(layout)) {
    mode = "compact";
  } else if ((width > 0 && width < compactMaxWidth) || (height > 0 && height < compactMaxHeight)) {
    mode = "compact";
  } else if (width >= wideMinWidth && height >= wideMinHeight) {
    mode = "wide";
  } else if (height >= tallMinHeight) {
    mode = "tall";
  }

  return {
    layout,
    width,
    height,
    mode,
    compact: mode === "compact",
    standard: mode === "standard",
    tall: mode === "tall",
    wide: mode === "wide",
  };
}
