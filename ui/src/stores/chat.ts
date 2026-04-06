import { create } from "zustand";
import type { Message, SSEEvent } from "../types/api";

type ToolCall = {
  name: string;
  args?: string;
  status: "running" | "done" | "awaiting_approval" | "denied";
  approvalId?: string;
  approvalReason?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
};

/** State for a single concurrent member bot stream (keyed by stream_id). */
export interface MemberStreamState {
  botId: string;
  botName: string;
  streamingContent: string;
  thinkingContent: string;
  toolCalls: ToolCall[];
  error?: string;
}

interface ChatChannelState {
  messages: Message[];
  streamingContent: string;
  thinkingContent: string;
  isStreaming: boolean;
  /** True when this tab initiated the stream (vs observing another tab's stream). */
  isLocalStream: boolean;
  isProcessing: boolean;
  queuedTaskId: string | null;
  toolCalls: ToolCall[];
  correlationId: string | null;
  error: string | null;
  secretWarning: { patterns: { type: string }[] } | null;
  /** Bot currently responding (for multi-bot channels). */
  respondingBotId: string | null;
  respondingBotName: string | null;
  /** Concurrent member bot streams, keyed by stream_id. */
  memberStreams: Record<string, MemberStreamState>;
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
  /** Remove all cached state for a channel (call on channel deletion). */
  deleteChannel: (channelId: string) => void;
  /** Start tracking a concurrent member bot stream. */
  startMemberStream: (channelId: string, streamId: string, botId: string, botName: string) => void;
  /** Route a stream event to the correct member stream. */
  handleMemberStreamEvent: (channelId: string, streamId: string, event: SSEEvent) => void;
  /** Finalize a member stream — materialize as message and remove entry. */
  finishMemberStream: (channelId: string, streamId: string) => void;
}

const emptyChannel: ChatChannelState = {
  messages: [],
  streamingContent: "",
  thinkingContent: "",
  isStreaming: false,
  isLocalStream: false,
  isProcessing: false,
  queuedTaskId: null,
  toolCalls: [],
  correlationId: null,
  error: null,
  secretWarning: null,
  respondingBotId: null,
  respondingBotName: null,
  memberStreams: {},
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
            isLocalStream: true,
            isProcessing: false,
            queuedTaskId: null,
            streamingContent: "",
            thinkingContent: "",
            toolCalls: [],
            correlationId: null,
            error: null,
            secretWarning: null,
            respondingBotId: null,
            respondingBotName: null,
            memberStreams: {},
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
        case "pending_tasks": {
          // Deferred delegations / scheduled tasks were created during this turn.
          // Switch to background polling so the UI picks up results when they arrive.
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, isProcessing: true },
            },
          };
        }
        case "cancelled": {
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, isStreaming: false, streamingContent: "", thinkingContent: "", toolCalls: [], respondingBotId: null, respondingBotName: null },
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
        case "approval_request": {
          const data = event.data as {
            approval_id?: string;
            tool?: string;
            reason?: string;
            capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
          };
          const updated = [...ch.toolCalls];
          const last = updated.findLastIndex((t) => t.status === "running" && t.name === data.tool);
          if (last >= 0) {
            updated[last] = {
              ...updated[last],
              status: "awaiting_approval",
              approvalId: data.approval_id,
              approvalReason: data.reason ?? undefined,
              capability: data.capability ?? undefined,
            };
          }
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, toolCalls: updated },
            },
          };
        }
        case "approval_resolved": {
          const data = event.data as { approval_id?: string; verdict?: string };
          const updated = [...ch.toolCalls];
          const idx = updated.findIndex((t) => t.approvalId === data.approval_id);
          if (idx >= 0) {
            const newStatus = data.verdict === "approved" ? "running" as const : "denied" as const;
            updated[idx] = { ...updated[idx], status: newStatus };
          }
          return {
            channels: {
              ...s.channels,
              [channelId]: { ...ch, toolCalls: updated },
            },
          };
        }
        case "delegation_post": {
          // Immediate delegation result — add as a synthetic message so it's
          // visible during streaming rather than waiting for the DB refetch.
          const data = event.data as { bot_id?: string; text?: string; display_name?: string };
          if (!data.text) return s;
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                messages: [
                  ...ch.messages,
                  {
                    id: `delegation-${Date.now()}`,
                    session_id: "",
                    role: "assistant" as const,
                    content: data.text,
                    created_at: new Date().toISOString(),
                    metadata: {
                      passive: true,
                      delegated_by: data.bot_id,
                      delegated_by_display: data.display_name,
                    },
                  },
                ],
              },
            },
          };
        }
        case "stream_meta": {
          const data = event.data as { responding_bot_id?: string; responding_bot_name?: string };
          return {
            channels: {
              ...s.channels,
              [channelId]: {
                ...ch,
                respondingBotId: data.responding_bot_id ?? ch.respondingBotId,
                respondingBotName: data.responding_bot_name ?? ch.respondingBotName,
              },
            },
          };
        }
        case "pending_member_stream": {
          // Legacy event — no longer needed with stream_id-based demuxing.
          // Kept for backward compat but ignored.
          return s;
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

      // Also materialize any lingering member streams (e.g. cancel while
      // member bots are still streaming — stream_end may never arrive).
      let memberMessages = newMessages;
      for (const [sid, stream] of Object.entries(ch.memberStreams)) {
        if (stream.streamingContent) {
          memberMessages = [
            ...memberMessages,
            {
              id: `member-${sid}`,
              session_id: "",
              role: "assistant" as const,
              content: stream.streamingContent,
              created_at: new Date().toISOString(),
              metadata: { trigger: "member_mention", sender_type: "bot" },
            },
          ];
        }
      }

      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            messages: memberMessages,
            isStreaming: false,
            isLocalStream: false,
            // Preserve isProcessing/queuedTaskId — if a "queued" event set these,
            // we must NOT clear them here. The SSE closes after "queued" which
            // triggers finishStreaming, but the background task is still running.
            // clearProcessing() handles the reset when the task actually completes.
            streamingContent: "",
            thinkingContent: "",
            toolCalls: [],
            correlationId: null,
            respondingBotId: null,
            respondingBotName: null,
            memberStreams: {},
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
          respondingBotId: null,
          respondingBotName: null,
          memberStreams: {},
        },
      },
    })),

  deleteChannel: (channelId) =>
    set((s) => {
      const { [channelId]: _, ...rest } = s.channels;
      return { channels: rest };
    }),

  // ---- Member stream actions (for parallel multi-bot) ----

  startMemberStream: (channelId, streamId, botId, botName) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            memberStreams: {
              ...ch.memberStreams,
              [streamId]: {
                botId,
                botName,
                streamingContent: "",
                thinkingContent: "",
                toolCalls: [],
              },
            },
          },
        },
      };
    }),

  handleMemberStreamEvent: (channelId, streamId, event) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      const stream = ch.memberStreams[streamId];
      if (!stream) return s;

      let updated: MemberStreamState;
      switch (event.event) {
        case "text_delta": {
          const data = event.data as { delta?: string };
          updated = { ...stream, streamingContent: stream.streamingContent + (data.delta ?? "") };
          break;
        }
        case "thinking": {
          const data = event.data as { delta?: string };
          updated = { ...stream, thinkingContent: stream.thinkingContent + (data.delta ?? "") };
          break;
        }
        case "thinking_content": {
          const data = event.data as { text?: string };
          updated = { ...stream, thinkingContent: data.text ?? stream.thinkingContent };
          break;
        }
        case "assistant_text": {
          const data = event.data as { text?: string };
          updated = { ...stream, streamingContent: data.text ?? stream.streamingContent };
          break;
        }
        case "response": {
          const data = event.data as { text?: string };
          updated = { ...stream, streamingContent: data.text ?? stream.streamingContent };
          break;
        }
        case "tool_start": {
          const data = event.data as { tool?: string; args?: string };
          updated = {
            ...stream,
            toolCalls: [
              ...stream.toolCalls,
              { name: data.tool ?? "unknown", args: data.args, status: "running" },
            ],
          };
          break;
        }
        case "tool_result": {
          const tcs = [...stream.toolCalls];
          const last = tcs.findLastIndex((t) => t.status === "running");
          if (last >= 0) tcs[last] = { ...tcs[last], status: "done" };
          updated = { ...stream, toolCalls: tcs };
          break;
        }
        case "error": {
          const data = event.data as { message?: string; detail?: string };
          updated = { ...stream, error: data.message ?? data.detail ?? "Error" };
          break;
        }
        default:
          return s; // Ignore unknown events for member streams
      }

      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            memberStreams: { ...ch.memberStreams, [streamId]: updated },
          },
        },
      };
    }),

  finishMemberStream: (channelId, streamId) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      const stream = ch.memberStreams[streamId];
      if (!stream) return s;

      // Materialize the member stream's content as a message
      let messages = ch.messages;
      if (stream.streamingContent) {
        const toolsUsed = stream.toolCalls.length > 0
          ? stream.toolCalls.map((tc) => tc.name)
          : undefined;
        const metadata: Record<string, any> = {
          ...(toolsUsed ? { tools_used: toolsUsed } : {}),
          trigger: "member_mention",
          sender_type: "bot",
        };
        messages = [
          ...messages,
          {
            id: `member-${streamId}`,
            session_id: "",
            role: "assistant" as const,
            content: stream.streamingContent,
            created_at: new Date().toISOString(),
            metadata,
          },
        ];
      }

      // Remove this stream from memberStreams
      const { [streamId]: _, ...remaining } = ch.memberStreams;
      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            messages,
            memberStreams: remaining,
          },
        },
      };
    }),
}));
