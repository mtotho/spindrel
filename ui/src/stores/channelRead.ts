import { create } from "zustand";

interface ChannelReadState {
  /** Map of channelId -> unread agent reply count from the server. */
  unreadByChannel: Record<string, number>;
  /** Optimistic local clear while the server mark-read request completes. */
  markRead: (channelId: string) => void;
  /** Returns true if the server has unread agent replies for the channel. */
  isUnread: (channelId: string, updatedAt: string | undefined) => boolean;
  setChannelUnread: (channelId: string | null | undefined, count: number) => void;
  setMany: (counts: Record<string, number>) => void;
  /** Remove tracking for a deleted channel */
  deleteChannel: (channelId: string) => void;
}

export const useChannelReadStore = create<ChannelReadState>()((set, get) => ({
  unreadByChannel: {},
  markRead: (channelId) => get().setChannelUnread(channelId, 0),
  isUnread: (channelId) => (get().unreadByChannel[channelId] ?? 0) > 0,
  setChannelUnread: (channelId, count) => {
    if (!channelId) return;
    set((s) => ({
      unreadByChannel: {
        ...s.unreadByChannel,
        [channelId]: Math.max(0, count),
      },
    }));
  },
  setMany: (counts) => set({ unreadByChannel: counts }),
  deleteChannel: (channelId) =>
    set((s) => {
      const { [channelId]: _, ...rest } = s.unreadByChannel;
      return { unreadByChannel: rest };
    }),
}));
