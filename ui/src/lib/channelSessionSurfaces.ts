export type ChannelSessionSurface =
  | { kind: "primary" }
  | { kind: "channel"; sessionId: string }
  | { kind: "scratch"; sessionId: string };

export type ChannelSessionPanel = Extract<ChannelSessionSurface, { kind: "channel" | "scratch" }>;

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

export interface ChannelSessionSearchMatch {
  kind: "message" | "section";
  source: string;
  preview?: string | null;
  message_id?: string | null;
  section_id?: string | null;
  section_sequence?: number | null;
}

export interface ChannelSessionCatalogItem {
  session_id: string;
  surface_kind: "channel" | "scratch";
  bot_id: string;
  created_at: string;
  last_active: string;
  label?: string | null;
  summary?: string | null;
  preview?: string | null;
  message_count: number;
  section_count: number;
  is_active: boolean;
  is_current: boolean;
  matches?: ChannelSessionSearchMatch[];
}

export type ChannelSessionPickerEntry =
  | {
      kind: "primary";
      id: "primary";
      surface: Extract<ChannelSessionSurface, { kind: "primary" }>;
      label: string;
      meta: string;
      selected: boolean;
      matches?: ChannelSessionSearchMatch[];
    }
  | {
      kind: "channel";
      id: string;
      surface: Extract<ChannelSessionSurface, { kind: "channel" }>;
      row: ChannelSessionCatalogItem;
      label: string;
      meta: string;
      selected: boolean;
      matches?: ChannelSessionSearchMatch[];
    }
  | {
      kind: "scratch";
      id: string;
      surface: Extract<ChannelSessionSurface, { kind: "scratch" }>;
      row: (ScratchSessionLike & { session_id: string }) | ChannelSessionCatalogItem;
      label: string;
      meta: string;
      selected: boolean;
      matches?: ChannelSessionSearchMatch[];
    };

export function normalizeChannelSessionPanels(value: unknown): ChannelSessionPanel[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isChannelSessionPanel)
    .slice(0, MAX_CHANNEL_SESSION_PANELS);
}

function isChannelSessionPanel(panel: unknown): panel is ChannelSessionPanel {
  return !!panel
    && typeof panel === "object"
    && "kind" in panel
    && "sessionId" in panel
    && (panel.kind === "scratch" || panel.kind === "channel")
    && typeof panel.sessionId === "string"
    && panel.sessionId.length > 0;
}

export function addChannelSessionPanel(
  current: readonly ChannelSessionPanel[],
  surface: ChannelSessionPanel,
): ChannelSessionPanel[] {
  const { kind, sessionId } = surface;
  if (!sessionId) return normalizeChannelSessionPanels(current);
  const existing = normalizeChannelSessionPanels(current).filter(
    (panel) => panel.kind !== kind || panel.sessionId !== sessionId,
  );
  const next: ChannelSessionPanel[] = [...existing, { kind, sessionId }];
  return next.slice(-MAX_CHANNEL_SESSION_PANELS);
}

export function removeChannelSessionPanel(
  current: readonly ChannelSessionPanel[],
  target: ChannelSessionPanel | string,
): ChannelSessionPanel[] {
  return current
    .filter(isChannelSessionPanel)
    .filter((panel) => {
      if (typeof target === "string") return panel.sessionId !== target;
      return panel.kind !== target.kind || panel.sessionId !== target.sessionId;
    })
    .slice(0, MAX_CHANNEL_SESSION_PANELS);
}

export function buildChannelSessionRoute(channelId: string, surface: ChannelSessionSurface): string {
  if (surface.kind === "primary") return `/channels/${channelId}`;
  if (surface.kind === "channel") return `/channels/${channelId}`;
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

export function buildChannelSessionChatSource({
  channelId,
  botId,
  sessionId,
}: {
  channelId: string;
  botId?: string | null;
  sessionId: string;
}) {
  return {
    kind: "session" as const,
    sessionId,
    parentChannelId: channelId,
    botId: botId ?? undefined,
    externalDelivery: "none" as const,
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

export function getChannelSessionMeta(session: ChannelSessionCatalogItem): string {
  const bits = [
    session.is_active ? "Primary" : "Previous",
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
  channelSessions,
  deepMatches,
  query,
}: {
  channelLabel?: string | null;
  selectedSessionId?: string | null;
  history?: ScratchSessionLike[] | null;
  channelSessions?: ChannelSessionCatalogItem[] | null;
  deepMatches?: ChannelSessionCatalogItem[] | null;
  query?: string;
}): ChannelSessionPickerEntry[] {
  const deepById = new Map((deepMatches ?? []).map((row) => [row.session_id, row]));
  if (channelSessions && channelSessions.length > 0) {
    const seen = new Set<string>();
    const rows: ChannelSessionPickerEntry[] = [];
    for (const base of channelSessions) {
      const row = deepById.get(base.session_id) ?? base;
      seen.add(row.session_id);
      if (row.surface_kind === "scratch") {
        rows.push({
          kind: "scratch",
          id: row.session_id,
          surface: { kind: "scratch", sessionId: row.session_id },
          row,
          label: row.label?.trim() || row.summary?.trim() || row.preview?.trim() || "Untitled session",
          meta: getChannelSessionMeta(row),
          selected: selectedSessionId === row.session_id,
          matches: row.matches ?? [],
        });
      } else if (row.is_active) {
        rows.push({
          kind: "primary",
          id: "primary",
          surface: { kind: "primary" },
          label: "Primary session",
          meta: getChannelSessionMeta(row),
          selected: !selectedSessionId,
          matches: row.matches ?? [],
        });
      } else {
        rows.push({
          kind: "channel",
          id: row.session_id,
          surface: { kind: "channel", sessionId: row.session_id },
          row,
          label: row.label?.trim() || row.summary?.trim() || row.preview?.trim() || row.session_id.slice(0, 8),
          meta: getChannelSessionMeta(row),
          selected: false,
          matches: row.matches ?? [],
        });
      }
    }
    for (const row of deepMatches ?? []) {
      if (seen.has(row.session_id)) continue;
      rows.push(row.surface_kind === "scratch" ? {
        kind: "scratch",
        id: row.session_id,
        surface: { kind: "scratch", sessionId: row.session_id },
        row,
        label: row.label?.trim() || row.summary?.trim() || row.preview?.trim() || "Untitled session",
        meta: getChannelSessionMeta(row),
        selected: selectedSessionId === row.session_id,
        matches: row.matches ?? [],
      } : {
        kind: "channel",
        id: row.session_id,
        surface: { kind: "channel", sessionId: row.session_id },
        row,
        label: row.label?.trim() || row.summary?.trim() || row.preview?.trim() || row.session_id.slice(0, 8),
        meta: getChannelSessionMeta(row),
        selected: false,
        matches: row.matches ?? [],
      });
    }

    const q = query?.trim().toLowerCase();
    const filtered = q
      ? rows.filter((entry) => {
          const snippets = (entry.matches ?? []).map((m) => m.preview ?? "").join(" ");
          return `${entry.label} ${entry.meta} ${snippets}`.toLowerCase().includes(q)
            || (entry.matches?.length ?? 0) > 0;
        })
      : rows;
    return [...filtered].sort((a, b) => (b.matches?.length ?? 0) - (a.matches?.length ?? 0));
  }

  const primary: ChannelSessionPickerEntry = {
    kind: "primary",
    id: "primary",
    surface: { kind: "primary" },
    label: "Primary session",
    meta: channelLabel ? `Default conversation for #${channelLabel}` : "Default channel conversation",
    selected: !selectedSessionId,
    matches: [],
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
      matches: [],
    }));

  const entries = [primary, ...scratchRows];
  const q = query?.trim().toLowerCase();
  if (!q) return entries;
  return entries.filter((entry) => `${entry.label} ${entry.meta}`.toLowerCase().includes(q));
}
