/**
 * paletteOverrides — context-scoped overrides for how CommandPalette
 * resolves a selection AND which surface owns the active palette session.
 *
 * Default behavior: pick → navigate. The spatial canvas registers a
 * channel-pick (and widget-pick) handler so picking a tile flies the camera
 * instead of routing away, and sets `surface = "canvas"` so the palette can
 * render canvas-aware grouping (Canvas tools first, on-map items second).
 *
 * Single global slot per concern (most-recently-registered wins). Owner
 * registers on mount, clears on unmount.
 */
import { create } from "zustand";
import type { PaletteItem } from "../components/palette/types";

export type PaletteSurface = "canvas" | null;

interface PaletteOverridesState {
  /** Returns true if the override consumed the selection (palette should NOT navigate). */
  channelPick: ((channelId: string) => boolean) | null;
  setChannelPick: (handler: ((channelId: string) => boolean) | null) => void;
  /** Same contract as channelPick, for widget tiles pinned to the canvas. */
  widgetPick: ((widgetId: string) => boolean) | null;
  setWidgetPick: (handler: ((widgetId: string) => boolean) | null) => void;
  /** Active surface — drives canvas-aware rendering in CommandPaletteContent. */
  surface: PaletteSurface;
  setSurface: (surface: PaletteSurface) => void;
  /** Surface-contributed palette items (e.g. widgets on the spatial canvas). */
  extraItems: PaletteItem[];
  setExtraItems: (items: PaletteItem[]) => void;
  /** Channel ids that exist as spatial nodes on the canvas. */
  onMapChannelIds: Set<string>;
  setOnMapChannelIds: (ids: Set<string>) => void;
}

export const usePaletteOverrides = create<PaletteOverridesState>((set) => ({
  channelPick: null,
  setChannelPick: (handler) => set({ channelPick: handler }),
  widgetPick: null,
  setWidgetPick: (handler) => set({ widgetPick: handler }),
  surface: null,
  setSurface: (surface) => set({ surface }),
  extraItems: [],
  setExtraItems: (items) => set({ extraItems: items }),
  onMapChannelIds: new Set<string>(),
  setOnMapChannelIds: (ids) => set({ onMapChannelIds: ids }),
}));
