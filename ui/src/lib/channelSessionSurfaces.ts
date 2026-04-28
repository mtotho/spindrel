export type ChannelSessionSurface =
  | { kind: "primary" }
  | { kind: "channel"; sessionId: string }
  | { kind: "scratch"; sessionId: string };

export type ChannelSessionPanel = Extract<ChannelSessionSurface, { kind: "channel" | "scratch" }>;

export type ChannelSessionActivationIntent = "switch" | "split";

export const MAX_CHANNEL_SESSION_PANELS = 2;
export const MAX_CHANNEL_CHAT_PANES = 3;

export interface ChannelChatPane {
  id: string;
  surface: ChannelSessionSurface;
  channelId?: string;
}

export interface ChannelChatPaneLayout {
  panes: ChannelChatPane[];
  focusedPaneId: string | null;
  widths: Record<string, number>;
  maximizedPaneId: string | null;
  miniPane: ChannelChatPane | null;
}

export interface ChannelSessionPickerGroup {
  id: "current" | "primary" | "recent" | "results";
  label: string;
  entries: ChannelSessionPickerEntry[];
}

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

export function surfaceKey(surface: ChannelSessionSurface): string {
  if (surface.kind === "primary") return "primary";
  return `${surface.kind}:${surface.sessionId}`;
}

export function paneIdForSurface(surface: ChannelSessionSurface): string {
  return surfaceKey(surface);
}

function isChannelSessionSurface(value: unknown): value is ChannelSessionSurface {
  if (!value || typeof value !== "object" || !("kind" in value)) return false;
  if (value.kind === "primary") return true;
  return (value.kind === "scratch" || value.kind === "channel")
    && "sessionId" in value
    && typeof value.sessionId === "string"
    && value.sessionId.length > 0;
}

function isChannelChatPane(value: unknown): value is ChannelChatPane {
  return !!value
    && typeof value === "object"
    && "id" in value
    && typeof value.id === "string"
    && "surface" in value
    && isChannelSessionSurface(value.surface);
}

function normalizeWidths(panes: readonly ChannelChatPane[], input: unknown): Record<string, number> {
  const raw = input && typeof input === "object" ? input as Record<string, unknown> : {};
  const count = Math.max(1, panes.length);
  const fallback = 1 / count;
  const widths: Record<string, number> = {};
  let total = 0;
  for (const pane of panes) {
    const width = typeof raw[pane.id] === "number" && Number.isFinite(raw[pane.id] as number)
      ? Math.max(0.12, raw[pane.id] as number)
      : fallback;
    widths[pane.id] = width;
    total += width;
  }
  if (total <= 0) {
    for (const pane of panes) widths[pane.id] = fallback;
    return widths;
  }
  for (const pane of panes) widths[pane.id] = widths[pane.id] / total;
  return widths;
}

export function defaultChannelChatPaneLayout(): ChannelChatPaneLayout {
  const primary: ChannelChatPane = { id: "primary", surface: { kind: "primary" } };
  return {
    panes: [primary],
    focusedPaneId: primary.id,
    widths: { [primary.id]: 1 },
    maximizedPaneId: null,
    miniPane: null,
  };
}

export function normalizeChannelChatPaneLayout(
  value: unknown,
  legacyPanels?: unknown,
): ChannelChatPaneLayout {
  const raw = value && typeof value === "object" ? value as Partial<ChannelChatPaneLayout> : null;
  let panes = Array.isArray(raw?.panes)
    ? raw.panes.filter(isChannelChatPane)
    : [];
  if (panes.length === 0) {
    panes = defaultChannelChatPaneLayout().panes;
    for (const panel of normalizeChannelSessionPanels(legacyPanels)) {
      panes.push({ id: paneIdForSurface(panel), surface: panel });
    }
  }
  const deduped: ChannelChatPane[] = [];
  const seen = new Set<string>();
  for (const pane of panes) {
    const id = pane.id || paneIdForSurface(pane.surface);
    if (seen.has(id)) continue;
    seen.add(id);
    deduped.push({ ...pane, id });
    if (deduped.length >= MAX_CHANNEL_CHAT_PANES) break;
  }
  const focusedPaneId = typeof raw?.focusedPaneId === "string"
    && deduped.some((pane) => pane.id === raw.focusedPaneId)
    ? raw.focusedPaneId
    : (deduped[0]?.id ?? null);
  const maximizedPaneId = typeof raw?.maximizedPaneId === "string"
    && deduped.some((pane) => pane.id === raw.maximizedPaneId)
    ? raw.maximizedPaneId
    : null;
  const miniPane = isChannelChatPane(raw?.miniPane) ? raw.miniPane : null;
  return {
    panes: deduped,
    focusedPaneId,
    widths: normalizeWidths(deduped, raw?.widths),
    maximizedPaneId,
    miniPane,
  };
}

export function addChannelChatPane(
  layout: ChannelChatPaneLayout,
  surface: ChannelSessionSurface,
): ChannelChatPaneLayout {
  const id = paneIdForSurface(surface);
  const existing = normalizeChannelChatPaneLayout(layout);
  const panes = existing.panes.some((pane) => pane.id === id)
    ? existing.panes
    : [...existing.panes, { id, surface }].slice(-MAX_CHANNEL_CHAT_PANES);
  return {
    panes,
    focusedPaneId: id,
    widths: normalizeWidths(panes, existing.widths),
    maximizedPaneId: existing.maximizedPaneId && panes.some((pane) => pane.id === existing.maximizedPaneId)
      ? existing.maximizedPaneId
      : null,
    miniPane: existing.miniPane?.id === id ? null : existing.miniPane,
  };
}

export function replaceFocusedChannelChatPane(
  layout: ChannelChatPaneLayout,
  surface: ChannelSessionSurface,
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  const nextId = paneIdForSurface(surface);
  const targetId = existing.focusedPaneId ?? existing.panes[0]?.id;
  const withoutDuplicate = existing.panes.filter((pane) => pane.id !== nextId);
  const index = Math.max(0, withoutDuplicate.findIndex((pane) => pane.id === targetId));
  const panes = withoutDuplicate.length === 0
    ? [{ id: nextId, surface }]
    : withoutDuplicate.map((pane, paneIndex) => paneIndex === index ? { id: nextId, surface } : pane);
  return {
    panes,
    focusedPaneId: nextId,
    widths: normalizeWidths(panes, existing.widths),
    maximizedPaneId: existing.maximizedPaneId === targetId ? nextId : null,
    miniPane: existing.miniPane?.id === nextId ? null : existing.miniPane,
  };
}

export function removeChannelChatPane(
  layout: ChannelChatPaneLayout,
  paneId: string,
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  const panes = existing.panes.filter((pane) => pane.id !== paneId);
  return {
    panes,
    focusedPaneId: panes[0]?.id ?? null,
    widths: normalizeWidths(panes, existing.widths),
    maximizedPaneId: existing.maximizedPaneId === paneId ? null : existing.maximizedPaneId,
    miniPane: existing.miniPane?.id === paneId ? null : existing.miniPane,
  };
}

export function moveChannelChatPane(
  layout: ChannelChatPaneLayout,
  paneId: string,
  direction: "left" | "right",
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  const index = existing.panes.findIndex((pane) => pane.id === paneId);
  if (index < 0) return existing;
  const nextIndex = direction === "left" ? index - 1 : index + 1;
  if (nextIndex < 0 || nextIndex >= existing.panes.length) return existing;
  const panes = [...existing.panes];
  const current = panes[index]!;
  panes[index] = panes[nextIndex]!;
  panes[nextIndex] = current;
  return {
    ...existing,
    panes,
    widths: normalizeWidths(panes, existing.widths),
  };
}

export function maximizeChannelChatPane(
  layout: ChannelChatPaneLayout,
  paneId: string,
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  if (!existing.panes.some((pane) => pane.id === paneId)) return existing;
  return {
    ...existing,
    focusedPaneId: paneId,
    maximizedPaneId: paneId,
  };
}

export function restoreChannelChatPanes(layout: ChannelChatPaneLayout): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  return {
    ...existing,
    maximizedPaneId: null,
  };
}

export function minimizeChannelChatPane(
  layout: ChannelChatPaneLayout,
  paneId: string,
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  const pane = existing.panes.find((candidate) => candidate.id === paneId) ?? null;
  if (!pane) return existing;
  const panes = existing.panes.filter((candidate) => candidate.id !== paneId);
  return {
    panes,
    focusedPaneId: panes[0]?.id ?? null,
    widths: normalizeWidths(panes, existing.widths),
    maximizedPaneId: existing.maximizedPaneId === paneId ? null : existing.maximizedPaneId,
    miniPane: pane,
  };
}

export function restoreMiniChannelChatPane(layout: ChannelChatPaneLayout): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  if (!existing.miniPane) return existing;
  const pane = existing.miniPane;
  const panes = existing.panes.some((candidate) => candidate.id === pane.id)
    ? existing.panes
    : [...existing.panes, pane].slice(-MAX_CHANNEL_CHAT_PANES);
  return {
    panes,
    focusedPaneId: pane.id,
    widths: normalizeWidths(panes, existing.widths),
    maximizedPaneId: null,
    miniPane: null,
  };
}

export function channelChatPaneForSurface(surface: ChannelSessionSurface): ChannelChatPane {
  return { id: paneIdForSurface(surface), surface };
}

export function splitChannelChatPaneLayout(
  currentSurface: ChannelSessionSurface,
  nextSurface: ChannelSessionSurface,
): ChannelChatPaneLayout {
  const current = channelChatPaneForSurface(currentSurface);
  const next = channelChatPaneForSurface(nextSurface);
  const panes = current.id === next.id ? [current] : [current, next];
  return {
    panes,
    focusedPaneId: next.id,
    widths: normalizeWidths(panes, {}),
    maximizedPaneId: null,
    miniPane: null,
  };
}

export function resizeChannelChatPanes(
  layout: ChannelChatPaneLayout,
  leftPaneId: string,
  rightPaneId: string,
  deltaRatio: number,
): ChannelChatPaneLayout {
  const existing = normalizeChannelChatPaneLayout(layout);
  const widths = normalizeWidths(existing.panes, existing.widths);
  if (!(leftPaneId in widths) || !(rightPaneId in widths)) return existing;
  const left = widths[leftPaneId];
  const right = widths[rightPaneId];
  const total = left + right;
  const min = Math.min(0.4, total / 3);
  const nextLeft = Math.max(min, Math.min(total - min, left + deltaRatio));
  widths[leftPaneId] = nextLeft;
  widths[rightPaneId] = total - nextLeft;
  return {
    ...existing,
    widths: normalizeWidths(existing.panes, widths),
  };
}

export function buildChannelSessionRoute(channelId: string, surface: ChannelSessionSurface): string {
  if (surface.kind === "primary") return `/channels/${channelId}`;
  if (surface.kind === "channel") return `/channels/${channelId}/session/${surface.sessionId}?surface=channel`;
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
      } else {
        rows.push({
          kind: "channel",
          id: row.session_id,
          surface: { kind: "channel", sessionId: row.session_id },
          row,
          label: row.label?.trim() || row.summary?.trim() || row.preview?.trim() || row.session_id.slice(0, 8),
          meta: getChannelSessionMeta(row),
          selected: selectedSessionId === row.session_id || (!selectedSessionId && row.is_active),
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
        selected: selectedSessionId === row.session_id,
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

  const entries = scratchRows;
  const q = query?.trim().toLowerCase();
  if (!q) return entries;
  return entries.filter((entry) => `${entry.label} ${entry.meta}`.toLowerCase().includes(q));
}

export function buildChannelSessionPickerGroups(
  entries: readonly ChannelSessionPickerEntry[],
  query?: string,
): ChannelSessionPickerGroup[] {
  if (query?.trim()) {
    return [{ id: "results", label: "Results", entries: [...entries] }];
  }
  const current = entries.filter((entry) => entry.selected);
  const recent = entries
    .filter((entry) => (entry.kind === "channel" || entry.kind === "scratch") && !entry.selected)
    .sort((a, b) => recentEntryTimestamp(b) - recentEntryTimestamp(a));
  const groups: ChannelSessionPickerGroup[] = [
    { id: "current", label: "This chat", entries: current },
    { id: "recent", label: "Recent sessions", entries: recent },
  ];
  return groups.filter((group) => group.entries.length > 0);
}

function recentEntryTimestamp(entry: ChannelSessionPickerEntry): number {
  if (entry.kind === "primary") return 0;
  const row = entry.row as { last_active?: string | null; created_at?: string | null };
  const iso = row.last_active || row.created_at;
  if (!iso) return 0;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? ms : 0;
}
