import { create } from "zustand";

/** Remembers which scratch session the user is "inside" per channel, so a
 *  detour to the widget dashboard can bring them back to the same scratch
 *  context. Transient: not persisted; rehydrated on nav from the scratch
 *  full-page itself. */
interface ScratchReturnState {
  byChannel: Record<string, string>;
  setScratchReturn: (channelId: string, sessionId: string) => void;
  clearScratchReturn: (channelId: string) => void;
}

export const useScratchReturnStore = create<ScratchReturnState>((set) => ({
  byChannel: {},
  setScratchReturn: (channelId, sessionId) =>
    set((s) => {
      if (s.byChannel[channelId] === sessionId) return s;
      return { byChannel: { ...s.byChannel, [channelId]: sessionId } };
    }),
  clearScratchReturn: (channelId) =>
    set((s) => {
      if (!(channelId in s.byChannel)) return s;
      const { [channelId]: _, ...rest } = s.byChannel;
      return { byChannel: rest };
    }),
}));

/** Non-reactive read for imperative nav handlers. */
export function getScratchReturn(channelId: string): string | null {
  return useScratchReturnStore.getState().byChannel[channelId] ?? null;
}
