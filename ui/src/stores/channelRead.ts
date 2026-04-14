import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface ChannelReadState {
  /** Map of channelId -> ISO timestamp of last visit */
  lastVisitedAt: Record<string, string>;
  /** Call when user opens a channel */
  markRead: (channelId: string) => void;
  /** Returns true if channel has activity after last visit */
  isUnread: (channelId: string, updatedAt: string | undefined) => boolean;
  /** Remove tracking for a deleted channel */
  deleteChannel: (channelId: string) => void;
}

const storage = createJSONStorage(() => localStorage);

export const useChannelReadStore = create<ChannelReadState>()(
  persist(
    (set, get) => ({
      lastVisitedAt: {},
      markRead: (channelId) =>
        set((s) => ({
          lastVisitedAt: {
            ...s.lastVisitedAt,
            [channelId]: new Date().toISOString(),
          },
        })),
      isUnread: (channelId, updatedAt) => {
        if (!updatedAt) return false;
        const lastVisit = get().lastVisitedAt[channelId];
        if (!lastVisit) return true; // never visited = unread
        return new Date(updatedAt).getTime() > new Date(lastVisit).getTime();
      },
      deleteChannel: (channelId) =>
        set((s) => {
          const { [channelId]: _, ...rest } = s.lastVisitedAt;
          return { lastVisitedAt: rest };
        }),
    }),
    { name: "channel-read", storage }
  )
);
