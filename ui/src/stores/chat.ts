import { create } from "zustand";
import type {
  Message,
  SSEEvent,
  ToolCall as PersistedToolCall,
  ToolCallSummary,
  ToolResultEnvelope,
  ToolSurface,
} from "../types/api";

export type ToolCall = {
  id: string;
  name: string;
  args?: string;
  surface?: ToolSurface;
  summary?: ToolCallSummary | null;
  status: "running" | "done" | "awaiting_approval" | "denied";
  approvalId?: string;
  approvalReason?: string;
  capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
  isError?: boolean;
  /** Rendered tool result envelope (set on tool_result event). Drives the
   * mimetype-keyed renderer in <RichToolResult>. */
  envelope?: ToolResultEnvelope;
};

export type TurnTranscriptEntry =
  | {
      id: string;
      kind: "text";
      text: string;
    }
  | {
      id: string;
      kind: "tool_call";
      toolCallId: string;
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
  transcriptEntries: TurnTranscriptEntry[];
  autoInjectedSkills: AutoInjectedSkill[];
  correlationId?: string | null;
  /** Epoch ms when the slot was created. Used by the snapshot-reconcile
   * pass in useChannelState to decide whether a local turn that's missing
   * from the server snapshot is a ghost (kill it) or just-started and
   * racing the snapshot fetch (keep it). */
  startedAt: number;
  /** Epoch ms of the last SSE event applied to this turn. SSE activity is
   * proof of life: the reconciler must not kill a turn that is actively
   * streaming, even if the server snapshot hasn't caught up yet. */
  lastEventAt: number;
  error?: string;
  llmStatus?: {
    status: string; // "retry" | "fallback" | "cooldown_skip" | "error"
    model?: string;
    reason?: string;
    attempt?: number;
    maxRetries?: number;
    waitSeconds?: number;
    fallbackModel?: string;
    error?: string;
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
  /** Seed a turn from the server-side snapshot.
   *
   * Used by useChannelState on mount / SSE reconnect to rehydrate in-flight
   * turns whose SSE events predate the current subscription. Idempotent: if
   * the store already has live-SSE state for this turn (non-empty toolCalls
   * or autoInjectedSkills), the existing state wins so we don't clobber
   * fresher deltas with a staler snapshot. */
  rehydrateTurn: (
    channelId: string,
    turnId: string,
    botId: string,
    botName: string,
    isPrimary: boolean,
    toolCalls: ToolCall[],
    autoInjectedSkills: AutoInjectedSkill[],
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

function makeToolCallId(turnId: string, existingCount: number): string {
  return `${turnId}:tool:${existingCount + 1}`;
}

function appendTextEntry(entries: TurnTranscriptEntry[], delta: string): TurnTranscriptEntry[] {
  if (!delta) return entries;
  const next = [...entries];
  const last = next[next.length - 1];
  if (last?.kind === "text") {
    next[next.length - 1] = { ...last, text: last.text + delta };
    return next;
  }
  next.push({ id: `text:${next.length + 1}`, kind: "text", text: delta });
  return next;
}

function seedTranscriptFromToolCalls(toolCalls: ToolCall[]): TurnTranscriptEntry[] {
  return toolCalls.map((toolCall, index) => ({
    id: `tool:${index + 1}`,
    kind: "tool_call" as const,
    toolCallId: toolCall.id,
  }));
}

function toPersistedTranscriptEntries(entries: TurnTranscriptEntry[]): TurnTranscriptEntry[] | undefined {
  return entries.length > 0 ? entries.map((entry) => ({ ...entry })) : undefined;
}

function toPersistedToolCall(toolCall: ToolCall): PersistedToolCall {
  return {
    id: toolCall.id,
    name: toolCall.name,
    arguments: toolCall.args ?? "{}",
    ...(toolCall.surface ? { surface: toolCall.surface } : {}),
    ...(toolCall.summary ? { summary: toolCall.summary } : {}),
  };
}

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
                transcriptEntries: [],
                autoInjectedSkills: [],
                correlationId: turnId,
                startedAt: Date.now(),
                lastEventAt: Date.now(),
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

  rehydrateTurn: (channelId, turnId, botId, botName, isPrimary, toolCalls, autoInjectedSkills) =>
    set((s) => {
      const ch = s.channels[channelId] ?? emptyChannel;
      const existing = ch.turns[turnId];
      const hydratedToolCalls = toolCalls.map((toolCall, index) => ({
        ...toolCall,
        id: toolCall.id || makeToolCallId(turnId, index),
      }));
      // Live SSE state wins — a stale snapshot must not overwrite fresher
      // deltas. Only seed if the slot is absent or has no tool/skill state yet.
      if (existing && (existing.toolCalls.length > 0 || existing.autoInjectedSkills.length > 0)) {
        return s;
      }
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
                streamingContent: existing?.streamingContent ?? "",
                thinkingContent: existing?.thinkingContent ?? "",
                toolCalls: hydratedToolCalls,
                transcriptEntries:
                  existing?.transcriptEntries.length
                    ? existing.transcriptEntries
                    : seedTranscriptFromToolCalls(hydratedToolCalls),
                autoInjectedSkills,
                correlationId: turnId,
                startedAt: existing?.startedAt ?? Date.now(),
                lastEventAt: existing?.lastEventAt ?? Date.now(),
                llmStatus: existing?.llmStatus ?? null,
              },
            },
            isProcessing: false,
            queuedTaskId: null,
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
          const delta = data.delta ?? "";
          updated = {
            ...turn,
            streamingContent: turn.streamingContent + delta,
            transcriptEntries: appendTextEntry(turn.transcriptEntries, delta),
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
          const text = data.text || "";
          const shouldSeedTranscript = !turn.streamingContent && text;
          updated = {
            ...turn,
            streamingContent: turn.streamingContent || text,
            transcriptEntries: shouldSeedTranscript ? appendTextEntry(turn.transcriptEntries, text) : turn.transcriptEntries,
          };
          break;
        }
        case "response": {
          // Fallback for non-streaming providers. Don't replace if deltas
          // already populated streamingContent.
          const data = event.data as { text?: string };
          const text = data.text || "";
          const shouldSeedTranscript = !turn.streamingContent && text;
          updated = {
            ...turn,
            streamingContent: turn.streamingContent || text,
            transcriptEntries: shouldSeedTranscript ? appendTextEntry(turn.transcriptEntries, text) : turn.transcriptEntries,
          };
          break;
        }
        case "tool_start": {
          const data = event.data as {
            tool?: string;
            args?: string;
            surface?: ToolSurface;
            summary?: ToolCallSummary | null;
          };
          const toolCall: ToolCall = {
            id: makeToolCallId(turnId, turn.toolCalls.length),
            name: data.tool ?? "unknown",
            args: data.args,
            surface: data.surface,
            summary: data.summary ?? null,
            status: "running",
          };
          updated = {
            ...turn,
            toolCalls: [...turn.toolCalls, toolCall],
            transcriptEntries: [
              ...turn.transcriptEntries,
              { id: `tool:${toolCall.id}`, kind: "tool_call", toolCallId: toolCall.id },
            ],
          };
          break;
        }
        case "tool_result": {
          const data = event.data as {
            tool?: string;
            is_error?: boolean;
            envelope?: ToolResultEnvelope;
            surface?: ToolSurface;
            summary?: ToolCallSummary | null;
          };
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
              surface: data.surface ?? tcs[idx].surface,
              summary: data.summary ?? tcs[idx].summary ?? null,
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
            const toolCall: ToolCall = {
              id: makeToolCallId(turnId, tcs.length),
              name: data.tool ?? "approval",
              status: "awaiting_approval",
              approvalId: data.approval_id,
              approvalReason: data.reason ?? undefined,
              capability: data.capability ?? undefined,
            };
            tcs.push(toolCall);
            updated = {
              ...turn,
              toolCalls: tcs,
              transcriptEntries: [
                ...turn.transcriptEntries,
                { id: `tool:${toolCall.id}`, kind: "tool_call", toolCallId: toolCall.id },
              ],
            };
            break;
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
            error?: string;
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
              error: data.error,
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

      // SSE activity is proof of life — stamp lastEventAt so the
      // snapshot-reconcile pass in useChannelState won't kill a turn that
      // is still receiving deltas.
      const stamped: TurnState = { ...updated, lastEventAt: Date.now() };
      return {
        channels: {
          ...s.channels,
          [channelId]: {
            ...ch,
            turns: { ...ch.turns, [turnId]: stamped },
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
      const toolCalls = turn.toolCalls.length > 0
        ? turn.toolCalls.map(toPersistedToolCall)
        : undefined;
      const toolResults = turn.toolCalls.length > 0
        ? turn.toolCalls.map((tc) => tc.envelope)
        : undefined;
      const shouldMaterialize =
        !!turn.streamingContent ||
        !!turn.thinkingContent ||
        (toolResults?.length ?? 0) > 0 ||
        turn.autoInjectedSkills.length > 0;

      if (shouldMaterialize) {
        const toolsUsed = turn.toolCalls.length > 0
          ? turn.toolCalls.map((tc) => tc.name)
          : undefined;
        const transcriptEntries = toPersistedTranscriptEntries(turn.transcriptEntries);
        // Carry envelopes from the streaming turn into the synthetic message
        // so the rich tool result UI doesn't blink empty between finishTurn
        // and the session-messages refetch landing.
        const metadata: Record<string, any> = {
          ...(toolsUsed ? { tools_used: toolsUsed } : {}),
          ...(toolResults && toolResults.length > 0 ? { tool_results: toolResults } : {}),
          ...(transcriptEntries ? { transcript_entries: transcriptEntries } : {}),
          ...(turn.thinkingContent ? { thinking: turn.thinkingContent } : {}),
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
            ...(toolCalls ? { tool_calls: toolCalls } : {}),
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
