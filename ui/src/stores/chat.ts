import { create } from "zustand";
import type { Message, SSEEvent } from "../types/api";

interface ChatChannelState {
  messages: Message[];
  streamingContent: string;
  thinkingContent: string;
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
  thinkingContent: "",
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
          thinkingContent: "",
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
          // Server sends: {"type": "response", "text": "..."}
          const data = event.data as { text?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                streamingContent: data.text ?? ch.streamingContent,
              },
            },
          };
        }
        case "text_delta": {
          // Streaming text token
          const data = event.data as { delta?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                streamingContent: ch.streamingContent + (data.delta ?? ""),
              },
            },
          };
        }
        case "thinking": {
          // Streaming thinking/reasoning token
          const data = event.data as { delta?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                thinkingContent: ch.thinkingContent + (data.delta ?? ""),
              },
            },
          };
        }
        case "thinking_content": {
          // Consolidated thinking content (fallback for non-streaming path)
          const data = event.data as { text?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                thinkingContent: data.text ?? ch.thinkingContent,
              },
            },
          };
        }
        case "assistant_text": {
          // Intermediate text emitted alongside tool calls
          const data = event.data as { text?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                streamingContent: data.text ?? ch.streamingContent,
              },
            },
          };
        }
        case "tool_start": {
          // Server sends: {"type": "tool_start", "tool": "name", "args": "..."}
          const data = event.data as { tool?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                toolCalls: [
                  ...ch.toolCalls,
                  { name: data.tool ?? "unknown", status: "running" },
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
          // Server sends: {"type": "error", "message": "..."}
          const data = event.data as { message?: string; detail?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, error: data.message ?? data.detail ?? "Unknown error" },
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
            thinkingContent: "",
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
