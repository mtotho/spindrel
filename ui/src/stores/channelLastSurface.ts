import { create } from "zustand";

/**
 * Per-channel "last visited surface" memory. Used by:
 *   - Spatial canvas dive (`diveToChannel`) — navigates to the chat OR
 *     dashboard surface the user last opened for that channel, instead of
 *     always landing on `/channels/:id` chat.
 *   - Spatial canvas overlay (Ctrl+Shift+Space) — derives the channel id
 *     from EITHER the chat route (`/channels/:id`) or the dashboard route
 *     (`/widgets/channel/:id`) so "beam back up" reliably re-centers the
 *     camera on the tile the user dove from.
 *
 * Persistence: localStorage. Per-tab in-memory state mirrors it. Single
 * shared key so all tabs agree on the most-recent surface.
 */

export type ChannelSurface = "chat" | "dashboard";

const STORAGE_KEY = "channel.lastSurface";

function loadFromStorage(): Record<string, ChannelSurface> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const out: Record<string, ChannelSurface> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof k === "string" && (v === "chat" || v === "dashboard")) {
        out[k] = v;
      }
    }
    return out;
  } catch {
    return {};
  }
}

function saveToStorage(value: Record<string, ChannelSurface>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* storage disabled */
  }
}

interface ChannelLastSurfaceState {
  byChannel: Record<string, ChannelSurface>;
  setSurface: (channelId: string, surface: ChannelSurface) => void;
}

export const useChannelLastSurface = create<ChannelLastSurfaceState>((set, get) => ({
  byChannel: loadFromStorage(),
  setSurface: (channelId, surface) => {
    if (!channelId) return;
    if (get().byChannel[channelId] === surface) return;
    const next = { ...get().byChannel, [channelId]: surface };
    set({ byChannel: next });
    saveToStorage(next);
  },
}));

export function getChannelLastSurface(channelId: string): ChannelSurface | null {
  return useChannelLastSurface.getState().byChannel[channelId] ?? null;
}

// URL → (channelId, surface). Single source of truth for matching either
// the chat or dashboard route shape, used by the AppShell tracker AND the
// SpatialCanvasOverlay's contextual-camera derivation.
const CHAT_RE = /^\/channels\/([0-9a-f-]+)/i;
const DASH_RE = /^\/widgets\/channel\/([0-9a-f-]+)/i;

export function parseChannelSurfaceFromPath(
  pathname: string,
): { channelId: string; surface: ChannelSurface } | null {
  const chat = pathname.match(CHAT_RE);
  if (chat) return { channelId: chat[1]!, surface: "chat" };
  const dash = pathname.match(DASH_RE);
  if (dash) return { channelId: dash[1]!, surface: "dashboard" };
  return null;
}

export function buildChannelSurfaceRoute(
  channelId: string,
  surface: ChannelSurface,
): string {
  return surface === "dashboard"
    ? `/widgets/channel/${channelId}`
    : `/channels/${channelId}`;
}
