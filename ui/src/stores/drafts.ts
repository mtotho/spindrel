import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

/** Serializable version of a pending file attachment. */
export interface DraftFile {
  name: string;
  type: string;
  size: number;
  base64: string;
  preview?: string; // data URL for images — rebuilt from base64 on restore
}

interface DraftEntry {
  text: string;
  files: DraftFile[];
}

interface DraftsState {
  drafts: Record<string, DraftEntry>;
  getDraft: (channelId: string) => DraftEntry;
  setDraftText: (channelId: string, text: string) => void;
  setDraftFiles: (channelId: string, files: DraftFile[]) => void;
  clearDraft: (channelId: string) => void;
}

const emptyDraft: DraftEntry = { text: "", files: [] };

export const useDraftsStore = create<DraftsState>()(
  persist(
    (set, get) => ({
      drafts: {},

      getDraft: (channelId) => get().drafts[channelId] ?? emptyDraft,

      setDraftText: (channelId, text) =>
        set((s) => ({
          drafts: {
            ...s.drafts,
            [channelId]: { ...(s.drafts[channelId] ?? emptyDraft), text },
          },
        })),

      setDraftFiles: (channelId, files) =>
        set((s) => ({
          drafts: {
            ...s.drafts,
            [channelId]: { ...(s.drafts[channelId] ?? emptyDraft), files },
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
