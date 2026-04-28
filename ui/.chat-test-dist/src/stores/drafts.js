import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
const emptyDraft = { text: "", files: [] };
export const useDraftsStore = create()(persist((set, get) => ({
    drafts: {},
    getDraft: (channelId) => get().drafts[channelId] ?? emptyDraft,
    setDraftText: (channelId, text) => set((s) => ({
        drafts: {
            ...s.drafts,
            [channelId]: { ...(s.drafts[channelId] ?? emptyDraft), text },
        },
    })),
    setDraftFiles: (channelId, files) => set((s) => ({
        drafts: {
            ...s.drafts,
            [channelId]: { ...(s.drafts[channelId] ?? emptyDraft), files },
        },
    })),
    clearDraft: (channelId) => set((s) => {
        const { [channelId]: _, ...rest } = s.drafts;
        return { drafts: rest };
    }),
}), {
    name: "chat-drafts",
    storage: createJSONStorage(() => localStorage),
}));
