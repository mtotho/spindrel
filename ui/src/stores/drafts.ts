import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface DraftEntry {
  text: string;
}

interface DraftsState {
  drafts: Record<string, DraftEntry>;
  getDraft: (channelId: string) => DraftEntry;
  setDraftText: (channelId: string, text: string) => void;
  clearDraft: (channelId: string) => void;
}

const emptyDraft: DraftEntry = { text: "" };

export const useDraftsStore = create<DraftsState>()(
  persist(
    (set, get) => ({
      drafts: {},

      getDraft: (channelId) => get().drafts[channelId] ?? emptyDraft,

      setDraftText: (channelId, text) =>
        set((s) => ({
          drafts: {
            ...s.drafts,
            [channelId]: { text },
          },
        })),

      clearDraft: (channelId) =>
        set((s) => {
          const { [channelId]: _, ...rest } = s.drafts;
          return { drafts: rest };
        }),
    }),
    {
      name: "chat-drafts",
      storage: createJSONStorage(() => localStorage),
    }
  )
);
