import { create } from "zustand";
import type { Message, SSEEvent, ToolResultEnvelope } from "../types/api";

type ToolCall = {
  name: string;
  args?: string;
  status: "running" | "done" | "awaiting_approval" | "denied";
  approvalId?: string;
  approvalReason?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
  isError?: boolean;
  /** Rendered tool result envelope (set on tool_result event). Drives the
   * mimetype-keyed renderer in <RichToolResult>. */
  envelope?: ToolResultEnvelope;
};

/**
 * State for a single in-flight agent turn.
 *
 * Every concurrent turn — primary bot or member bot — has an entry keyed
 * by its `turn_id` (assigned by the backend in TurnStartedPayload). The
 * UI renders one StreamingIndicator per turn, ordered by `isPrimary`
 * (channel's primary bot first) then insertion order.
 */
type AutoInjectedSkill = {
  skillId: string;
  skillName: string;
  similarity: number;
  source: string;
};

export interface TurnState {
  botId: string;
  botName: string;
  isPrimary: boolean;
  streamingContent: string;
  thinkingContent: string;
  toolCalls: ToolCall[];
  autoInjectedSkills: AutoInjectedSkill[];
  correlationId?: string | null;
  error?: string;
  llmStatus?: {
    status: string; // "retry" | "fallback" | "cooldown_skip"
    model?: string;
    reason?: string;
    attempt?: number;
    maxRetries?: number;
    waitSeconds?: number;
    fallbackModel?: string;
  } | null;
}

interface ChatChannelState {
  messages: Message[];
  /** All in-flight turns, keyed by turn_id. */
  turns: Record<string, TurnState>;
  /** Background-task processing (e.g. queued message running on the server). */
  isProcessing: boolean;
  queuedTaskId: string | null;
  error: string | null;
  secretWarning: { patterns: { type: string }[] } | null;
  /** Latest context budget published by the agent loop. */
  contextBudget: { utilization: number; consumed: number; total: number } | null;
}

interface ChatState {
  channels: Record<string, ChatChannelState>;
  getChannel: (channelId: string) => ChatChannelState;
  addMessage: (channelId: string, message: Message) => void;
  setMessages: (channelId: string, messages: Message[]) => void;
  /** Begin tracking a new turn for the channel. */
  startTurn: (
    channelId: string,
    turnId: string,
    botId: string,
    botName: string,
    isPrimary: boolean,
  ) => void;
  /** Apply an event to the matching turn slot. */
  handleTurnEvent: (channelId: string, turnId: string, event: SSEEvent) => void;
  /** Finalize a turn — materialize as a synthetic message and remove the slot. */
  finishTurn: (channelId: string, turnId: string) => void;
  clearProcessing: (channelId: string) => void;
  setError: (channelId: string, error: string) => void;
  /** Remove all cached state for a channel (call on channel deletion). */
  deleteChannel: (channelId: string) => void;
  /** Mark the channel as background-processing (e.g. queued task accepted). */
  setProcessing: (channelId: string, taskId: string | null) => void;
  /** Set a secret-pattern warning surfaced from the secret-check pre-flight. */
  setSecretWarning: (channelId: string, warning: { patterns: { type: string }[] } | null) => void;
  /** Update the latest context budget for the channel. */
  setContextBudget: (
    channelId: string,
    budget: { utilization: number; consumed: number; total: number } | null,
  ) => void;
}

const emptyChannel: ChatChannelState = {
  messages: [],
  turns: {},
  isProcessing: false,
  queuedTaskId: null,
  error: null,
  secretWarning: null,
  contextBudget: null,
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

  startTurn: (channelId, turnId, botId, botName, isPrimary) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      // Idempotent: if a turn with this id already exists (e.g. SSE
      // replay after reconnect), keep the existing slot.
      if (ch.turns[turnId]) return s;
      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            turns: {
              ...ch.turns,
              [turnId]: {
                botId,
                botName,
                isPrimary,
                streamingContent: "",
                thinkingContent: "",
                toolCalls: [],
                autoInjectedSkills: [],
                correlationId: turnId,
                llmStatus: null,
              },
            },
            // A new turn implies the channel is no longer in the
            // queued/processing intermediate state.
            isProcessing: false,
            queuedTaskId: null,
            error: null,
          },
        },
      };
    }),

  handleTurnEvent: (channelId, turnId, event) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      const turn = ch.turns[turnId];
      if (!turn) return s;

      let updated: TurnState;
      switch (event.event) {
        case "text_delta": {
          const data = event.data as { delta?: string };
          updated = {
            ...turn,
            streamingContent: turn.streamingContent + (data.delta ?? ""),
            llmStatus: null, // Clear retry status — actual content is flowing
          };
          break;
        }
        case "thinking": {
          const data = event.data as { delta?: string };
          updated = {
            ...turn,
            thinkingContent: turn.thinkingContent + (data.delta ?? ""),
          };
          break;
        }
        case "thinking_content": {
          const data = event.data as { text?: string };
          updated = { ...turn, thinkingContent: data.text ?? turn.thinkingContent };
          break;
        }
        case "assistant_text": {
          // Don't replace — text_deltas already accumulated the canonical content.
          const data = event.data as { text?: string };
          updated = {
            ...turn,
            streamingContent: turn.streamingContent || data.text || "",
          };
          break;
        }
        case "response": {
          // Fallback for non-streaming providers. Don't replace if deltas
          // already populated streamingContent.
          const data = event.data as { text?: string };
          updated = {
            ...turn,
            streamingContent: turn.streamingContent || data.text || "",
          };
          break;
        }
        case "tool_start": {
          const data = event.data as { tool?: string; args?: string };
          updated = {
            ...turn,
            toolCalls: [
              ...turn.toolCalls,
              { name: data.tool ?? "unknown", args: data.args, status: "running" },
            ],
          };
          break;
        }
        case "tool_result": {
          const data = event.data as { tool?: string; is_error?: boolean; envelope?: ToolResultEnvelope };
          const tcs = [...turn.toolCalls];
          // Match the tool by name (last running entry with that name)
          // so concurrent tool calls don't get mismatched.
          let idx = -1;
          for (let i = tcs.length - 1; i >= 0; i--) {
            if (tcs[i].status === "running" && (!data.tool || tcs[i].name === data.tool)) {
              idx = i;
              break;
            }
          }
          if (idx >= 0) {
            tcs[idx] = {
              ...tcs[idx],
              status: "done",
              isError: data.is_error || tcs[idx].isError,
              envelope: data.envelope ?? tcs[idx].envelope,
            };
          }
          updated = { ...turn, toolCalls: tcs };
          break;
        }
        case "approval_request": {
          const data = event.data as {
            approval_id?: string;
            tool?: string;
            reason?: string;
            capability?: TurnState["toolCalls"][number]["capability"];
          };
          const tcs = [...turn.toolCalls];
          let idx = -1;
          for (let i = tcs.length - 1; i >= 0; i--) {
            if (tcs[i].status === "running" && (!data.tool || tcs[i].name === data.tool)) {
              idx = i;
              break;
            }
          }
          if (idx >= 0) {
            tcs[idx] = {
              ...tcs[idx],
              status: "awaiting_approval",
              approvalId: data.approval_id,
              approvalReason: data.reason ?? undefined,
              capability: data.capability ?? undefined,
            };
          } else {
            // Approval arrived without a preceding tool_start (capability
            // approval gates can fire before the call). Synthesize one.
            tcs.push({
              name: data.tool ?? "approval",
              status: "awaiting_approval",
              approvalId: data.approval_id,
              approvalReason: data.reason ?? undefined,
              capability: data.capability ?? undefined,
            });
          }
          updated = { ...turn, toolCalls: tcs };
          break;
        }
        case "approval_resolved": {
          const data = event.data as { approval_id?: string; verdict?: string; decision?: string };
          const verdict = data.verdict ?? data.decision;
          const tcs = [...turn.toolCalls];
          const idx = tcs.findIndex((t) => t.approvalId === data.approval_id);
          if (idx >= 0) {
            const newStatus = verdict === "approved" ? ("running" as const) : ("denied" as const);
            tcs[idx] = { ...tcs[idx], status: newStatus };
          }
          updated = { ...turn, toolCalls: tcs };
          break;
        }
        case "skill_auto_inject": {
          const data = event.data as { skill_id?: string; skill_name?: string; similarity?: number; source?: string };
          updated = {
            ...turn,
            autoInjectedSkills: [
              ...turn.autoInjectedSkills,
              {
                skillId: data.skill_id ?? "",
                skillName: data.skill_name ?? "Unknown",
                similarity: data.similarity ?? 0,
                source: data.source ?? "unknown",
              },
            ],
          };
          break;
        }
        case "llm_status": {
          const data = event.data as {
            status?: string;
            model?: string;
            reason?: string;
            attempt?: number;
            max_retries?: number;
            wait_seconds?: number;
            fallback_model?: string;
          };
          updated = {
            ...turn,
            llmStatus: {
              status: data.status ?? "retry",
              model: data.model,
              reason: data.reason,
              attempt: data.attempt,
              maxRetries: data.max_retries,
              waitSeconds: data.wait_seconds,
              fallbackModel: data.fallback_model,
            },
          };
          break;
        }
        case "error": {
          const data = event.data as { message?: string; detail?: string };
          updated = { ...turn, error: data.message ?? data.detail ?? "Error" };
          break;
        }
        default:
          return s;
      }

      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            turns: { ...ch.turns, [turnId]: updated },
          },
        },
      };
    }),

  finishTurn: (channelId, turnId) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      const turn = ch.turns[turnId];
      if (!turn) return s;

      // Materialize the turn's content as a synthetic message.
      let messages = ch.messages;
      if (turn.streamingContent) {
        const toolsUsed = turn.toolCalls.length > 0
          ? turn.toolCalls.map((tc) => tc.name)
          : undefined;
        // Carry envelopes from the streaming turn into the synthetic message
        // so the rich tool result UI doesn't blink empty between finishTurn
        // and the session-messages refetch landing.
        const toolResults = turn.toolCalls.length > 0
          ? turn.toolCalls.map((tc) => tc.envelope ?? null).filter((e): e is NonNullable<typeof e> => e !== null)
          : undefined;
        const metadata: Record<string, any> = {
          ...(toolsUsed ? { tools_used: toolsUsed } : {}),
          ...(toolResults && toolResults.length > 0 ? { tool_results: toolResults } : {}),
          ...(turn.botName ? { sender_display_name: turn.botName } : {}),
          ...(turn.botId ? { sender_id: `bot:${turn.botId}` } : {}),
          ...(turn.isPrimary ? {} : { trigger: "member_mention", sender_type: "bot" }),
          ...(turn.autoInjectedSkills.length > 0 ? { auto_injected_skills: turn.autoInjectedSkills } : {}),
        };
        const hasMetadata = Object.keys(metadata).length > 0;
        messages = [
          ...messages,
          {
            id: `turn-${turnId}`,
            session_id: "",
            role: "assistant" as const,
            content: turn.streamingContent,
            created_at: new Date().toISOString(),
            ...(turn.correlationId ? { correlation_id: turn.correlationId } : {}),
            ...(hasMetadata ? { metadata } : {}),
          },
        ];
      }

      const { [turnId]: _removed, ...remaining } = ch.turns;
      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            messages,
            turns: remaining,
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

  setProcessing: (channelId, taskId) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          isProcessing: true,
          queuedTaskId: taskId,
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
        },
      },
    })),

  setSecretWarning: (channelId, warning) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          secretWarning: warning,
        },
      },
    })),

  setContextBudget: (channelId, budget) =>
    set((s) => ({
      channels: {
        ...s.channels,
        [channelId]: {
          ...(s.channels[channelId] ?? emptyChannel),
          contextBudget: budget,
        },
      },
    })),

  deleteChannel: (channelId) =>
    set((s) => {
      const { [channelId]: _, ...rest } = s.channels;
      return { channels: rest };
    }),
}));

/** Convenience selector — true when the channel has at least one in-flight turn. */
export function selectIsStreaming(state: ChatChannelState): boolean {
  return Object.keys(state.turns).length > 0;
}
