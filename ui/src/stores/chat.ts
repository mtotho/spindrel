import { create } from "zustand";
import type { Message, SSEEvent } from "../types/api";

interface ChatChannelState {
  messages: Message[];
  streamingContent: string;
  isStreaming: boolean;
  toolCalls: { name: string; status: "running" | "done" }[];
  error: string | null;
}

interface ChatState {
  channels: Record<string, ChatChannelState>;
  getChannel: (channelId: string) => ChatChannelState;
  addMessage: (channelId: string, message: Message) => void;
  setMessages: (channelId: string, messages: Message[]) => void;
  startStreaming: (channelId: string) => void;
  handleSSEEvent: (channelId: string, event: SSEEvent) => void;
  finishStreaming: (channelId: string) => void;
  setError: (channelId: string, error: string) => void;
}

const emptyChannel: ChatChannelState = {
  messages: [],
  streamingContent: "",
  isStreaming: false,
  toolCalls: [],
  error: null,
};

export const useChatStore = create<ChatState>()((set, get) => ({
  channels: {},

  getChannel: (channelId) => get().channels[channelId] ?? emptyChannel,

  setMessages: (channelId, messages) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: { ...(s.channels[channelId] ?? emptyChannel), messages },
      },
    })),

  addMessage: (channelId, message) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      return {
        channels: {
          ...s.channels,
          [channelId]: { ...ch, messages: [...ch.messages, message] },
        },
      };
    }),

  startStreaming: (channelId) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          isStreaming: true,
          streamingContent: "",
          toolCalls: [],
          error: null,
        },
      },
    })),

  handleSSEEvent: (channelId, event) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      switch (event.event) {
        case "response": {
          const data = event.data as { response?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                streamingContent: data.response ?? ch.streamingContent,
              },
            },
          };
        }
        case "tool_start": {
          const data = event.data as { tool_name?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                toolCalls: [
                  ...ch.toolCalls,
                  { name: data.tool_name ?? "unknown", status: "running" },
                ],
              },
            },
          };
        }
        case "tool_result": {
          const updated = [...ch.toolCalls];
          const last = updated.findLastIndex((t) => t.status === "running");
          if (last >= 0) updated[last] = { ...updated[last], status: "done" };
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, toolCalls: updated },
            },
          };
        }
        case "error": {
          const data = event.data as { error?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, error: data.error ?? "Unknown error" },
            },
          };
        }
        default:
          return s;
      }
    }),

  finishStreaming: (channelId) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      // Convert streaming content to a real message
      const newMessages = ch.streamingContent
        ? [
            ...ch.messages,
            {
              id: `msg-${Date.now()}`,
              session_id: "",
              role: "assistant" as const,
              content: ch.streamingContent,
              created_at: new Date().toISOString(),
            },
          ]
        : ch.messages;

      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            messages: newMessages,
            isStreaming: false,
            streamingContent: "",
            toolCalls: [],
          },
        },
      };
    }),

  setError: (channelId, error) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          error,
          isStreaming: false,
        },
      },
    })),
}));
