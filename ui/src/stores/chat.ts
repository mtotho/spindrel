import { create } from "zustand";
import type { Message, SSEEvent } from "../types/api";

interface ChatChannelState {
  messages: Message[];
  streamingContent: string;
  thinkingContent: string;
  isStreaming: boolean;
  isProcessing: boolean;
  queuedTaskId: string | null;
  toolCalls: { name: string; args?: string; status: "running" | "done" }[];
  correlationId: string | null;
  error: string | null;
  secretWarning: { patterns: { type: string }[] } | null;
}

interface ChatState {
  channels: Record<string, ChatChannelState>;
  getChannel: (channelId: string) => ChatChannelState;
  addMessage: (channelId: string, message: Message) => void;
  setMessages: (channelId: string, messages: Message[]) => void;
  startStreaming: (channelId: string) => void;
  handleSSEEvent: (channelId: string, event: SSEEvent) => void;
  finishStreaming: (channelId: string) => void;
  clearProcessing: (channelId: string) => void;
  setError: (channelId: string, error: string) => void;
}

const emptyChannel: ChatChannelState = {
  messages: [],
  streamingContent: "",
  thinkingContent: "",
  isStreaming: false,
  isProcessing: false,
  queuedTaskId: null,
  toolCalls: [],
  correlationId: null,
  error: null,
  secretWarning: null,
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
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;

      // If already streaming with partial content, materialize it as a message
      // so it doesn't vanish when we reset the streaming buffer.
      let messages = ch.messages;
      if (ch.isStreaming && ch.streamingContent) {
        const toolsUsed = ch.toolCalls.length > 0
          ? ch.toolCalls.map((tc) => tc.name)
          : undefined;
        const metadata = toolsUsed ? { tools_used: toolsUsed } : undefined;
        messages = [
          ...messages,
          {
            id: `msg-${Date.now()}`,
            session_id: "",
            role: "assistant" as const,
            content: ch.streamingContent,
            created_at: new Date().toISOString(),
            correlation_id: ch.correlationId ?? undefined,
            metadata,
          },
        ];
      }

      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            messages,
            isStreaming: true,
            isProcessing: false,
            queuedTaskId: null,
            streamingContent: "",
            thinkingContent: "",
            toolCalls: [],
            correlationId: null,
            error: null,
            secretWarning: null,
          },
        },
      };
    }),

  handleSSEEvent: (channelId, event) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      switch (event.event) {
        case "response": {
          // Server sends: {"type": "response", "text": "...", "tools_used": [...], "correlation_id": "..."}
          const data = event.data as { text?: string; tools_used?: string[]; correlation_id?: string };
          // Capture tools_used from the response for persistence
          const updatedToolCalls = data.tools_used?.length
            ? data.tools_used.map((name) => ({ name, status: "done" as const }))
            : ch.toolCalls;
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                streamingContent: data.text ?? ch.streamingContent,
                toolCalls: updatedToolCalls,
                correlationId: data.correlation_id ?? ch.correlationId,
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
          const data = event.data as { tool?: string; args?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                toolCalls: [
                  ...ch.toolCalls,
                  { name: data.tool ?? "unknown", args: data.args, status: "running" },
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
        case "queued": {
          // Message was queued — SSE stream ends, switch to background processing mode
          const queuedData = event.data as { task_id?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                isStreaming: false,
                isProcessing: true,
                queuedTaskId: queuedData.task_id ?? null,
              },
            },
          };
        }
        case "cancelled": {
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, isStreaming: false, streamingContent: "", thinkingContent: "", toolCalls: [] },
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
        case "secret_warning": {
          const data = event.data as { patterns?: { type: string }[] };
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, secretWarning: { patterns: data.patterns ?? [] } },
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
      // Build metadata with tools_used if any tool calls were made
      const toolsUsed = ch.toolCalls.length > 0
        ? ch.toolCalls.map((tc) => tc.name)
        : undefined;
      const metadata = toolsUsed ? { tools_used: toolsUsed } : undefined;
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
              correlation_id: ch.correlationId ?? undefined,
              metadata,
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
            isProcessing: false,
            queuedTaskId: null,
            streamingContent: "",
            thinkingContent: "",
            toolCalls: [],
            correlationId: null,
          },
        },
      };
    }),

  clearProcessing: (channelId) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          isProcessing: false,
          queuedTaskId: null,
        },
      },
    })),

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
