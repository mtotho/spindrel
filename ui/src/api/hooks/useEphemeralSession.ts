import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

interface EphemeralContextPayload {
  page_name?: string;
  url?: string;
  tags?: string[];
  payload?: Record<string, unknown>;
  tool_hints?: string[];
}

interface SpawnEphemeralRequest {
  bot_id: string;
  parent_channel_id?: string;
  context?: EphemeralContextPayload;
}

interface SpawnEphemeralResponse {
  session_id: string;
  parent_channel_id: string | null;
}

/** Spawn an ephemeral session via POST /api/v1/sessions/ephemeral. */
export function useSpawnEphemeralSession() {
  return useMutation({
    mutationFn: (req: SpawnEphemeralRequest) =>
      apiFetch<SpawnEphemeralResponse>("/api/v1/sessions/ephemeral", {
        method: "POST",
        body: JSON.stringify(req),
      }),
  });
}

// ---------------------------------------------------------------------------
// Cross-device scratch-session pointer (Phase 3 — replaces localStorage-only
// identity for channel-scratch chats).
// ---------------------------------------------------------------------------

export interface ScratchSessionResponse {
  session_id: string;
  parent_channel_id: string;
  bot_id: string;
  created_at: string;
  is_current: boolean;
}

export interface ScratchHistoryItem {
  session_id: string;
  bot_id: string;
  created_at: string;
  last_active: string;
  is_current: boolean;
  message_count: number;
  preview?: string;
}

function scratchCurrentKey(parentChannelId: string, botId: string) {
  return ["scratch-current", parentChannelId, botId] as const;
}

function scratchHistoryKey(parentChannelId: string) {
  return ["scratch-history", parentChannelId] as const;
}

/** Resolve (or lazily create) the current scratch session for
 *  (user, channel, bot). Returns a stable session id that matches across
 *  devices for the authenticated user. */
export function useScratchSession(
  parentChannelId: string | null | undefined,
  botId: string | null | undefined,
) {
  const enabled = !!parentChannelId && !!botId;
  return useQuery({
    queryKey: enabled
      ? scratchCurrentKey(parentChannelId!, botId!)
      : ["scratch-current", "disabled"],
    queryFn: async (): Promise<ScratchSessionResponse> => {
      const qs = new URLSearchParams({
        parent_channel_id: parentChannelId!,
        bot_id: botId!,
      });
      return apiFetch<ScratchSessionResponse>(
        `/api/v1/sessions/scratch/current?${qs.toString()}`,
      );
    },
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** Reset: archive the current scratch session + spawn a fresh one. */
export function useResetScratchSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: { parent_channel_id: string; bot_id: string }) =>
      apiFetch<ScratchSessionResponse>("/api/v1/sessions/scratch/reset", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: scratchCurrentKey(vars.parent_channel_id, vars.bot_id),
      });
      qc.invalidateQueries({
        queryKey: scratchHistoryKey(vars.parent_channel_id),
      });
    },
  });
}

/** List the caller's scratch sessions (current + archived) for a channel. */
export function useScratchHistory(
  parentChannelId: string | null | undefined,
) {
  return useQuery({
    queryKey: parentChannelId
      ? scratchHistoryKey(parentChannelId)
      : ["scratch-history", "disabled"],
    queryFn: async (): Promise<ScratchHistoryItem[]> => {
      const qs = new URLSearchParams({
        parent_channel_id: parentChannelId!,
      });
      return apiFetch<ScratchHistoryItem[]>(
        `/api/v1/sessions/scratch/list?${qs.toString()}`,
      );
    },
    enabled: !!parentChannelId,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Storage helpers — persist {sessionId, botId} per surface key.
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = "spindrel:ephemeral:";

export interface StoredEphemeralState {
  sessionId: string;
  botId: string;
  /** Per-turn model override. Persisted so reloads keep the choice. */
  modelOverride?: string | null;
  /** Provider id that backs ``modelOverride`` (nullable when auto-routed). */
  modelProviderId?: string | null;
}

export function loadEphemeralState(storageKey: string): StoredEphemeralState | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) return null;
    return JSON.parse(raw) as StoredEphemeralState;
  } catch {
    return null;
  }
}

export function saveEphemeralState(storageKey: string, state: StoredEphemeralState): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(state));
  } catch {
    // localStorage may be unavailable (private mode etc.)
  }
}

export function clearEphemeralState(storageKey: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + storageKey);
  } catch {
    // ignore
  }
}
