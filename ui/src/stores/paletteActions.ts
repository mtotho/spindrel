/**
 * paletteActions — runtime registry of context-scoped command-palette actions.
 *
 * Global screens/views (e.g. the active channel) register their actions on
 * mount and unregister on unmount. CommandPalette reads this store and
 * merges the actions with its static navigation list.
 *
 * Actions are fire-and-forget callbacks (no href) — the palette invokes
 * `onSelect` directly instead of navigating.
 */
import { create } from "zustand";
import type { ComponentType } from "react";

export interface PaletteAction {
  /** Stable id for list keying + dedupe on re-register. */
  id: string;
  /** Display label (e.g. "Browse files in this channel"). */
  label: string;
  /** Short hint shown on the right (e.g. "#quality-assurance"). */
  hint?: string;
  /** Lucide icon component. */
  icon: ComponentType<{ size: number; color: string }>;
  /** Category bucket — "This Channel" for channel-scoped actions. */
  category: string;
  /** Handler fired when the palette item is selected. */
  onSelect: () => void;
}

interface PaletteActionsState {
  actions: PaletteAction[];
  /**
   * Register a group of actions under an `ownerKey` (e.g. `"channel:abc-123"`).
   * Any existing actions under that owner are replaced atomically. Returns
   * an unregister function, so effect cleanup is a one-liner.
   */
  register: (ownerKey: string, actions: PaletteAction[]) => () => void;
  unregister: (ownerKey: string) => void;
}

interface OwnedEntry {
  ownerKey: string;
  action: PaletteAction;
}

export const usePaletteActions = create<PaletteActionsState>((set, get) => {
  // Internal owned-entry list keyed by owner, flattened on read.
  let owned: OwnedEntry[] = [];

  const flush = () => set({ actions: owned.map((e) => e.action) });

  return {
    actions: [],
    register: (ownerKey, actions) => {
      owned = owned.filter((e) => e.ownerKey !== ownerKey).concat(
        actions.map((a) => ({ ownerKey, action: a })),
      );
      flush();
      return () => get().unregister(ownerKey);
    },
    unregister: (ownerKey) => {
      const before = owned.length;
      owned = owned.filter((e) => e.ownerKey !== ownerKey);
      if (owned.length !== before) flush();
    },
  };
});
