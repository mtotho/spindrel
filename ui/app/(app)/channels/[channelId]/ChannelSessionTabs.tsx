import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  closestCenter,
  DragOverlay,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  horizontalListSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2, Search, StickyNote, X } from "lucide-react";
import {
  buildChannelSessionPickerEntries,
  buildChannelSessionPickerGroups,
  surfaceKey,
  type ChannelSessionActivationIntent,
  type ChannelSessionSurface,
  type ChannelSessionTabItem,
} from "@/src/lib/channelSessionSurfaces";
import {
  useChannelSessionCatalog,
  useChannelSessionSearch,
} from "@/src/api/hooks/useChannelSessions";

interface ChannelSessionTabStripProps {
  tabs: ChannelSessionTabItem[];
  onSelect: (tab: ChannelSessionTabItem) => void;
  onFocusSplitPane: (tab: ChannelSessionTabItem, paneId: string) => void;
  onClose: (tab: ChannelSessionTabItem) => void;
  onReorder: (dragKey: string, targetKey: string) => void;
  onSplit: (tab: ChannelSessionTabItem) => void;
  onFocusOpenSurface: (tab: ChannelSessionTabItem) => void;
  onReplaceFocused: (tab: ChannelSessionTabItem) => void;
  onMakePrimary: (tab: ChannelSessionTabItem) => void;
  onOpenSessions?: () => void;
  openSurfaceKeys: string[];
  splitActive: boolean;
  pendingKey?: string | null;
}

export function ChannelSessionTabStrip({
  tabs,
  onSelect,
  onFocusSplitPane,
  onClose,
  onReorder,
  onSplit,
  onFocusOpenSurface,
  onReplaceFocused,
  onMakePrimary,
  onOpenSessions,
  openSurfaceKeys,
  splitActive,
  pendingKey,
}: ChannelSessionTabStripProps) {
  const tabKeys = useMemo(() => tabs.map((tab) => tab.key), [tabs]);
  const [activeDragKey, setActiveDragKey] = useState<string | null>(null);
  const activeDragTab = useMemo(
    () => tabs.find((tab) => tab.key === activeDragKey) ?? null,
    [activeDragKey, tabs],
  );
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 2 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragKey(String(event.active.id));
  };
  const handleDragEnd = (event: DragEndEvent) => {
    const activeKey = String(event.active.id);
    const overKey = event.over ? String(event.over.id) : null;
    setActiveDragKey(null);
    if (!overKey || activeKey === overKey) return;
    onReorder(activeKey, overKey);
  };
  if (tabs.length === 0) return null;
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setActiveDragKey(null)}
    >
      <div
        data-testid="channel-session-tab-strip"
        className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto px-3 pb-1 text-[12px]"
      >
        <SortableContext items={tabKeys} strategy={horizontalListSortingStrategy}>
          {tabs.map((tab) => (
            <SortableSessionTab
              key={tab.key}
              tab={tab}
              onSelect={onSelect}
              onFocusSplitPane={onFocusSplitPane}
              onClose={onClose}
              onSplit={onSplit}
              onFocusOpenSurface={onFocusOpenSurface}
              onReplaceFocused={onReplaceFocused}
              onMakePrimary={onMakePrimary}
              openSurfaceKeys={openSurfaceKeys}
              splitActive={splitActive}
              pending={pendingKey === tab.key}
            />
          ))}
        </SortableContext>
        {onOpenSessions && (
          <button
            type="button"
            onClick={onOpenSessions}
            className="ml-1 flex h-8 shrink-0 items-center rounded-md px-2 text-[11px] text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
          >
            More
          </button>
        )}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeDragTab ? <SessionTabDragGhost tab={activeDragTab} pending={pendingKey === activeDragTab.key} /> : null}
      </DragOverlay>
    </DndContext>
  );
}

interface SortableSessionTabProps {
  tab: ChannelSessionTabItem;
  onSelect: (tab: ChannelSessionTabItem) => void;
  onFocusSplitPane: (tab: ChannelSessionTabItem, paneId: string) => void;
  onClose: (tab: ChannelSessionTabItem) => void;
  onSplit: (tab: ChannelSessionTabItem) => void;
  onFocusOpenSurface: (tab: ChannelSessionTabItem) => void;
  onReplaceFocused: (tab: ChannelSessionTabItem) => void;
  onMakePrimary: (tab: ChannelSessionTabItem) => void;
  openSurfaceKeys: string[];
  splitActive: boolean;
  pending: boolean;
}

function SortableSessionTab({
  tab,
  onSelect,
  onFocusSplitPane,
  onClose,
  onSplit,
  onFocusOpenSurface,
  onReplaceFocused,
  onMakePrimary,
  openSurfaceKeys,
  splitActive,
  pending,
}: SortableSessionTabProps) {
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
  const surfaceOpen = tab.kind === "surface" && openSurfaceKeys.includes(surfaceKey(tab.surface));
  useEffect(() => {
    if (!menuPosition) return;
    const close = () => setMenuPosition(null);
    window.addEventListener("pointerdown", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [menuPosition]);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: tab.key });
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid="channel-session-tab"
      data-session-tab-key={tab.key}
      data-active={tab.active ? "true" : "false"}
      data-primary={tab.primary ? "true" : "false"}
      data-loading={pending ? "true" : "false"}
      data-reorderable="true"
      title={[tab.label, tab.meta].filter(Boolean).join("\n")}
      className={[
        "group relative flex h-8 shrink-0 touch-pan-x items-center gap-1 rounded-md px-1.5 text-left transition-colors",
        tab.kind === "split" ? "max-w-[360px]" : "max-w-[260px]",
        tab.active
          ? "bg-accent/[0.08] text-text"
          : "text-text-muted hover:bg-surface-overlay/60 hover:text-text",
        isDragging ? "z-10 opacity-30" : "",
        pending ? "bg-accent/[0.06]" : "",
      ].join(" ")}
      onClick={() => onSelect(tab)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelect(tab);
      }}
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
        setMenuPosition({ x: event.clientX, y: event.clientY });
      }}
      {...attributes}
      {...listeners}
    >
      <span
        aria-hidden="true"
        className="flex h-6 w-4 shrink-0 cursor-grab items-center justify-center rounded text-text-dim/60 transition-colors group-hover:bg-surface-overlay group-hover:text-text group-active:cursor-grabbing"
      >
        <GripVertical size={12} aria-hidden="true" />
      </span>
      {tab.kind === "split" ? (
        <div
          data-testid="channel-session-split-tab"
          className="flex min-w-0 flex-1 items-center gap-0.5"
        >
          {tab.panes.map((pane, index) => (
            <button
              key={pane.id}
              type="button"
              data-testid="channel-session-split-tab-pane"
              data-focused={pane.focused ? "true" : "false"}
              onClick={(event) => {
                event.stopPropagation();
                onFocusSplitPane(tab, pane.id);
              }}
              className={[
                "flex h-6 min-w-0 items-center gap-1 border border-surface-border/70 px-2 text-[11px] transition-colors",
                index === 0 ? "rounded-l-md" : "",
                index === tab.panes.length - 1 ? "rounded-r-md" : "",
                pane.focused ? "bg-accent/[0.10] text-text" : "bg-surface/60 text-text-muted hover:bg-surface-overlay/70 hover:text-text",
              ].join(" ")}
            >
              {pane.primary && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" aria-hidden="true" />}
              <span className="min-w-0 truncate">{pane.label}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {tab.primary && (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" aria-hidden="true" />
          )}
          <span className="min-w-0 truncate">{tab.label}</span>
          {tab.meta && (
            <span className="hidden shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim lg:inline">
              {tab.primary
                ? "Primary"
                : tab.kind === "surface" && tab.surface.kind === "scratch"
                  ? "Scratch"
                  : "Session"}
            </span>
          )}
        </div>
      )}
      {pending && <Loader2 size={11} className="shrink-0 animate-spin text-accent" aria-hidden="true" />}
      {tab.unreadCount > 0 && (
        <span
          data-testid="channel-session-tab-unread"
          className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-accent/15 px-1 text-[9px] font-semibold text-accent"
          title={`${tab.unreadCount} unread agent ${tab.unreadCount === 1 ? "reply" : "replies"}`}
        >
          {tab.unreadCount > 9 ? "9+" : tab.unreadCount}
        </span>
      )}
      <span
        className={[
          "absolute inset-x-2 bottom-0 h-px rounded-full transition-colors",
          tab.active ? "bg-accent/80" : "bg-transparent",
        ].join(" ")}
        aria-hidden="true"
      />
      <button
        type="button"
        aria-label={`Close ${tab.label} tab`}
        title="Close tab"
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onClose(tab);
        }}
        className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-dim opacity-70 transition-colors hover:bg-surface-overlay hover:text-text group-hover:opacity-100"
      >
        <X size={12} />
      </button>
      {menuPosition && (
        <div
          data-testid="channel-session-tab-menu"
          className="fixed z-40 w-52 rounded-md border border-surface-border bg-surface-raised p-1 shadow-lg"
          style={{ left: menuPosition.x, top: menuPosition.y }}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => {
              setMenuPosition(null);
              onSelect(tab);
            }}
            className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
          >
            {tab.kind === "split" ? "Open split" : "Open"}
          </button>
          {tab.kind === "split" ? (
            <>
              <div className="my-1 h-px bg-surface-border/60" />
              <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Focus pane</div>
              {tab.panes.map((pane) => (
                <button
                  key={pane.id}
                  type="button"
                  onClick={() => {
                    setMenuPosition(null);
                    onFocusSplitPane(tab, pane.id);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  {pane.label}
                </button>
              ))}
            </>
          ) : (
            <>
              {surfaceOpen ? (
                <button
                  type="button"
                  disabled={!splitActive}
                  onClick={() => {
                    setMenuPosition(null);
                    onFocusOpenSurface(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:text-text-dim disabled:opacity-50"
                >
                  {splitActive ? "Focus open pane" : "Already open"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setMenuPosition(null);
                    onSplit(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  Split right
                </button>
              )}
              {splitActive && !surfaceOpen && (
                <button
                  type="button"
                  onClick={() => {
                    setMenuPosition(null);
                    onReplaceFocused(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  Replace focused split
                </button>
              )}
              {tab.kind === "surface" && tab.surface.kind !== "primary" && (
                <button
                  type="button"
                  onClick={() => {
                    setMenuPosition(null);
                    onMakePrimary(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  Set as channel primary
                </button>
              )}
            </>
          )}
          <div className="my-1 h-px bg-surface-border/60" />
          <button
            type="button"
            onClick={() => {
              setMenuPosition(null);
              onClose(tab);
            }}
            className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-danger hover:bg-danger/10"
          >
            Close tab
          </button>
        </div>
      )}
    </div>
  );
}

function SessionTabDragGhost({
  tab,
  pending,
}: {
  tab: ChannelSessionTabItem;
  pending: boolean;
}) {
  return (
    <div
      className={[
        "flex h-8 max-w-[360px] items-center gap-1 rounded-md border border-surface-border/70 bg-surface-raised px-1.5 text-left text-[12px] text-text shadow-xl",
        tab.kind === "split" ? "min-w-[220px]" : "min-w-[160px]",
      ].join(" ")}
    >
      <span
        aria-hidden="true"
        className="flex h-6 w-4 shrink-0 items-center justify-center rounded text-text-dim/70"
      >
        <GripVertical size={12} aria-hidden="true" />
      </span>
      {tab.kind === "split" ? (
        <div className="flex min-w-0 flex-1 items-center gap-0.5">
          {tab.panes.map((pane, index) => (
            <span
              key={pane.id}
              className={[
                "flex h-6 min-w-0 items-center gap-1 border border-surface-border/70 px-2 text-[11px]",
                index === 0 ? "rounded-l-md" : "",
                index === tab.panes.length - 1 ? "rounded-r-md" : "",
                pane.focused ? "bg-accent/[0.10] text-text" : "bg-surface/60 text-text-muted",
              ].join(" ")}
            >
              {pane.primary && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" aria-hidden="true" />}
              <span className="min-w-0 truncate">{pane.label}</span>
            </span>
          ))}
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {tab.primary && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" aria-hidden="true" />}
          <span className="min-w-0 truncate">{tab.label}</span>
        </div>
      )}
      {pending && <Loader2 size={11} className="shrink-0 animate-spin text-accent" aria-hidden="true" />}
      {tab.unreadCount > 0 && (
        <span className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-accent/15 px-1 text-[9px] font-semibold text-accent">
          {tab.unreadCount > 9 ? "9+" : tab.unreadCount}
        </span>
      )}
    </div>
  );
}

interface ChannelSessionInlinePickerProps {
  channelId: string;
  channelLabel?: string | null;
  selectedSessionId?: string | null;
  onActivateSurface: (surface: ChannelSessionSurface, intent: ChannelSessionActivationIntent) => void;
  onOpenSessions?: () => void;
  onUnhideSurface?: (surface: ChannelSessionSurface) => void;
}

export function ChannelSessionInlinePicker({
  channelId,
  channelLabel,
  selectedSessionId,
  onActivateSurface,
  onOpenSessions,
  onUnhideSurface,
}: ChannelSessionInlinePickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const { data: channelSessions, isLoading, error } = useChannelSessionCatalog(channelId);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const {
    data: deepMatches,
    isFetching: deepSearchLoading,
    error: deepSearchError,
  } = useChannelSessionSearch(channelId, debouncedQuery);

  const entries = useMemo(
    () =>
      buildChannelSessionPickerEntries({
        channelLabel,
        selectedSessionId,
        channelSessions,
        deepMatches,
        query,
      }),
    [channelLabel, channelSessions, deepMatches, query, selectedSessionId],
  );
  const groups = useMemo(
    () => buildChannelSessionPickerGroups(entries, query),
    [entries, query],
  );

  return (
    <div
      data-testid="channel-session-inline-picker"
      className="flex min-h-0 flex-1 items-center justify-center bg-surface px-6 py-8"
    >
      <div className="flex w-full max-w-2xl flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-text">Choose a session</div>
            <div className="mt-1 text-[12px] text-text-dim">
              Closed tabs stay in history. Pick a recent session to bring it back.
            </div>
          </div>
          {onOpenSessions && (
            <button
              type="button"
              onClick={onOpenSessions}
              className="shrink-0 rounded-md px-3 py-1.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/[0.08]"
            >
              Full picker
            </button>
          )}
        </div>
        <label className="flex h-10 items-center gap-2 rounded-md bg-input px-3 text-sm text-text">
          <Search size={15} className="text-text-dim" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search recent sessions..."
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-text-dim"
          />
        </label>
        <div className="min-h-[220px] overflow-hidden rounded-md bg-surface-raised/35">
          {isLoading && <div className="px-4 py-8 text-sm text-text-dim">Loading sessions...</div>}
          {error && (
            <div className="px-4 py-8 text-sm text-danger">
              {error instanceof Error ? error.message : "Failed to load sessions."}
            </div>
          )}
          {!isLoading && !error && entries.length === 0 && (
            <div className="px-4 py-8 text-sm text-text-dim">No sessions matched that search.</div>
          )}
          {!isLoading && !error && groups.map((group) => (
            <div key={group.id} className="py-1">
              {groups.length > 1 && (
                <div className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                  {group.label}
                </div>
              )}
              {group.entries.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  data-testid="channel-session-inline-row"
                  data-session-row-key={surfaceKey(entry.surface)}
                  onClick={() => {
                    onUnhideSurface?.(entry.surface);
                    onActivateSurface(entry.surface, "switch");
                  }}
                  className="mx-1 flex w-[calc(100%-0.5rem)] items-start gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-surface-overlay/60"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-overlay text-text-dim">
                    <StickyNote size={14} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text">{entry.label}</span>
                    <span className="mt-0.5 block truncate text-[11px] text-text-dim">{entry.meta}</span>
                    {entry.matches && entry.matches.length > 0 && (
                      <span className="mt-1 block space-y-1">
                        {entry.matches.slice(0, 2).map((match, idx) => (
                          <span
                            key={`${match.kind}:${match.message_id ?? match.section_id ?? idx}`}
                            className="block truncate text-[11px] text-text-muted"
                          >
                            {match.kind === "section" ? "Section" : "Message"}: {match.preview}
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                  {entry.selected && (
                    <span className="shrink-0 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                      Current
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {deepSearchLoading && query.trim().length >= 2 && (
            <div className="px-4 py-2 text-[11px] text-text-dim">Searching message history...</div>
          )}
          {deepSearchError && (
            <div className="px-4 py-2 text-[11px] text-danger">
              {deepSearchError instanceof Error ? deepSearchError.message : "Deep search failed."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
