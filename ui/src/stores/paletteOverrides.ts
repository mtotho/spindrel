/**
 * paletteOverrides — context-scoped overrides for how CommandPalette
 * resolves a selection. Most consumers want default route navigation; the
 * spatial canvas registers a channel-pick override so picking a channel
 * flies the camera instead of routing away.
 *
 * Single global handler (most-recently-registered wins). The canvas
 * registers on mount, clears on unmount.
 */
import { create } from "zustand";

interface PaletteOverridesState {
  /** Returns true if the override consumed the selection (palette should NOT navigate). */
  channelPick: ((channelId: string) => boolean) | null;
  setChannelPick: (handler: ((channelId: string) => boolean) | null) => void;
}

export const usePaletteOverrides = create<PaletteOverridesState>((set) => ({
  channelPick: null,
  setChannelPick: (handler) => set({ channelPick: handler }),
}));
