export type ChannelSessionSurface =
  | { kind: "primary" }
  | { kind: "scratch"; sessionId: string };

export interface ChannelSessionPanel {
  kind: "scratch";
  sessionId: string;
}

export type ChannelSessionActivationIntent = "switch" | "split";

export const MAX_CHANNEL_SESSION_PANELS = 2;

export interface ScratchSessionLike {
  session_id?: string;
  bot_id?: string;
  created_at?: string;
  last_active?: string;
  is_current?: boolean;
  message_count?: number;
  preview?: string;
  title?: string | null;
  summary?: string | null;
  section_count?: number;
  session_scope?: string;
}

export type ChannelSessionPickerEntry =
  | {
      kind: "primary";
      id: "primary";
      surface: Extract<ChannelSessionSurface, { kind: "primary" }>;
      label: string;
      meta: string;
      selected: boolean;
    }
  | {
      kind: "scratch";
      id: string;
      surface: Extract<ChannelSessionSurface, { kind: "scratch" }>;
      row: ScratchSessionLike & { session_id: string };
      label: string;
      meta: string;
      selected: boolean;
    };

export function normalizeChannelSessionPanels(value: unknown): ChannelSessionPanel[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((panel): panel is ChannelSessionPanel =>
      !!panel
      && panel.kind === "scratch"
      && typeof panel.sessionId === "string"
      && panel.sessionId.length > 0,
    )
    .slice(0, MAX_CHANNEL_SESSION_PANELS);
}

export function addChannelSessionPanel(
  current: readonly ChannelSessionPanel[],
  sessionId: string,
): ChannelSessionPanel[] {
  if (!sessionId) return normalizeChannelSessionPanels(current);
  const existing = normalizeChannelSessionPanels(current).filter((panel) => panel.sessionId !== sessionId);
  const next: ChannelSessionPanel[] = [...existing, { kind: "scratch", sessionId }];
  return next.slice(-MAX_CHANNEL_SESSION_PANELS);
}

export function removeChannelSessionPanel(
  current: readonly ChannelSessionPanel[],
  sessionId: string,
): ChannelSessionPanel[] {
  return normalizeChannelSessionPanels(current).filter((panel) => panel.sessionId !== sessionId);
}

export function buildChannelSessionRoute(channelId: string, surface: ChannelSessionSurface): string {
  if (surface.kind === "primary") return `/channels/${channelId}`;
  return `/channels/${channelId}/session/${surface.sessionId}?scratch=true`;
}

export function buildScratchChatSource({
  channelId,
  botId,
  sessionId,
}: {
  channelId: string;
  botId?: string | null;
  sessionId?: string | null;
}) {
  return {
    kind: "ephemeral" as const,
    sessionStorageKey: `channel:${channelId}:scratch`,
    parentChannelId: channelId,
    defaultBotId: botId ?? undefined,
    context: {
      page_name: "channel_scratch",
      payload: { channel_id: channelId },
    },
    scratchBoundChannelId: channelId,
    pinnedSessionId: sessionId ?? undefined,
  };
}

export function formatScratchSessionTimestamp(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function getScratchSessionLabel(session: ScratchSessionLike): string {
  return session.title?.trim()
    || session.summary?.trim()
    || session.preview?.trim()
    || "Untitled session";
}

export function getScratchSessionStats(session: ScratchSessionLike): string {
  const messages = session.message_count ?? 0;
  const sections = session.section_count ?? 0;
  return `${messages} msg${messages === 1 ? "" : "s"} · ${sections} section${sections === 1 ? "" : "s"}`;
}

export function getScratchSessionMeta(session: ScratchSessionLike): string {
  const bits = [
    formatScratchSessionTimestamp(session.last_active || session.created_at),
    `${session.message_count ?? 0} msg${session.message_count === 1 ? "" : "s"}`,
    typeof session.section_count === "number"
      ? `${session.section_count} section${session.section_count === 1 ? "" : "s"}`
      : null,
  ].filter(Boolean);
  return bits.join(" · ");
}

export function isUntouchedDraftSession(session: ScratchSessionLike | null | undefined): boolean {
  if (!session) return false;
  if ((session.message_count ?? 0) !== 0 || (session.section_count ?? 0) !== 0) return false;
  if ((session.title || "").trim()) return false;
  if ((session.summary || "").trim()) return false;
  if ((session.preview || "").trim()) return false;
  return true;
}

export function buildChannelSessionPickerEntries({
  channelLabel,
  selectedSessionId,
  history,
  query,
}: {
  channelLabel?: string | null;
  selectedSessionId?: string | null;
  history?: ScratchSessionLike[] | null;
  query?: string;
}): ChannelSessionPickerEntry[] {
  const primary: ChannelSessionPickerEntry = {
    kind: "primary",
    id: "primary",
    surface: { kind: "primary" },
    label: "Primary session",
    meta: channelLabel ? `Default conversation for #${channelLabel}` : "Default channel conversation",
    selected: !selectedSessionId,
  };
  const scratchRows = (history ?? [])
    .filter((row): row is ScratchSessionLike & { session_id: string } =>
      typeof row.session_id === "string" && row.session_id.length > 0,
    )
    .map((row): ChannelSessionPickerEntry => ({
      kind: "scratch",
      id: row.session_id,
      surface: { kind: "scratch", sessionId: row.session_id },
      row,
      label: getScratchSessionLabel(row),
      meta: getScratchSessionMeta(row),
      selected: selectedSessionId === row.session_id,
    }));

  const entries = [primary, ...scratchRows];
  const q = query?.trim().toLowerCase();
  if (!q) return entries;
  return entries.filter((entry) => `${entry.label} ${entry.meta}`.toLowerCase().includes(q));
}
