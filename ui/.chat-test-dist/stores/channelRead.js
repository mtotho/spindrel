import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
const storage = createJSONStorage(() => localStorage);
export const useChannelReadStore = create()(persist((set, get) => ({
    lastVisitedAt: {},
    markRead: (channelId) => set((s) => ({
        lastVisitedAt: {
            ...s.lastVisitedAt,
            [channelId]: new Date().toISOString(),
        },
    })),
    isUnread: (channelId, updatedAt) => {
        if (!updatedAt)
            return false;
        const lastVisit = get().lastVisitedAt[channelId];
        if (!lastVisit)
            return true; // never visited = unread
        return new Date(updatedAt).getTime() > new Date(lastVisit).getTime();
    },
    deleteChannel: (channelId) => set((s) => {
        const { [channelId]: _, ...rest } = s.lastVisitedAt;
        return { lastVisitedAt: rest };
    }),
}), { name: "channel-read", storage }));
