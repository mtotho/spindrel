import { useMutation } from "@tanstack/react-query";
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
// Storage helpers — persist {sessionId, botId} per surface key.
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = "spindrel:ephemeral:";

export interface StoredEphemeralState {
  sessionId: string;
  botId: string;
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
