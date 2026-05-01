import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import ReactDOM from "react-dom";
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
import {
  FileText,
  GripVertical,
  Loader2,
  MoreHorizontal,
  Search,
  StickyNote,
  X,
} from "lucide-react";
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
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

export interface ChannelFileTabItem {
  kind: "file";
  key: string;
  path: string;
  label: string;
  meta: string | null;
  active: boolean;
  primary: false;
  closeable: true;
  unreadCount: 0;
  splitActive: boolean;
}

export type ChannelTopTabItem = ChannelSessionTabItem | ChannelFileTabItem;

interface ChannelSessionTabStripProps {
  tabs: ChannelTopTabItem[];
  onSelect: (tab: ChannelTopTabItem) => void;
  onFocusSplitPane: (tab: ChannelTopTabItem, paneId: string) => void;
  onClose: (tab: ChannelTopTabItem) => void;
  onPromote: (tab: ChannelTopTabItem) => void;
  onReorder: (dragKey: string, targetKey: string) => void;
  onSplit: (tab: ChannelTopTabItem) => void;
  onUnsplitPane: (tab: ChannelTopTabItem, paneId: string) => void;
  onFocusOpenSurface: (tab: ChannelTopTabItem) => void;
  onReplaceFocused: (tab: ChannelTopTabItem) => void;
  onMakePrimary: (tab: ChannelTopTabItem) => void;
  canRenameSession: (tab: ChannelTopTabItem) => boolean;
  onRenameSession: (tab: ChannelTopTabItem, title: string) => void;
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
  onPromote,
  onReorder,
  onSplit,
  onUnsplitPane,
  onFocusOpenSurface,
  onReplaceFocused,
  onMakePrimary,
  canRenameSession,
  onRenameSession,
  openSurfaceKeys,
  splitActive,
  pendingKey,
}: ChannelSessionTabStripProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const overflowButtonRef = useRef<HTMLButtonElement | null>(null);
  const overflowMenuRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [tabWidths, setTabWidths] = useState<Record<string, number>>({});
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [overflowMenuPosition, setOverflowMenuPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);
  useLayoutEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const update = () => setContainerWidth(node.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const node = measureRef.current;
    if (!node) return;
    const measure = () => {
      const next: Record<string, number> = {};
      node
        .querySelectorAll<HTMLElement>("[data-measure-tab-key]")
        .forEach((child) => {
          next[child.dataset.measureTabKey ?? ""] = Math.ceil(
            child.getBoundingClientRect().width,
          );
        });
      setTabWidths(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [tabs]);
  const { visibleTabs, overflowTabs } = useMemo(() => {
    if (tabs.length === 0)
      return { visibleTabs: tabs, overflowTabs: [] as ChannelTopTabItem[] };
    const available = Math.max(0, containerWidth - 24);
    if (!available)
      return { visibleTabs: tabs, overflowTabs: [] as ChannelTopTabItem[] };
    const gap = 4;
    const overflowButtonWidth = 60;
    const visible: ChannelTopTabItem[] = [];
    const hidden: ChannelTopTabItem[] = [];
    let used = 0;
    for (let index = 0; index < tabs.length; index++) {
      const tab = tabs[index]!;
      const width = tabWidths[tab.key] ?? (tab.kind === "split" ? 240 : 170);
      const remainingAfterThis = tabs.length - index - 1;
      const reserve = remainingAfterThis > 0 ? overflowButtonWidth + gap : 0;
      const nextUsed = used + (visible.length > 0 ? gap : 0) + width;
      if (visible.length === 0 || nextUsed + reserve <= available) {
        visible.push(tab);
        used = nextUsed;
      } else {
        hidden.push(tab);
      }
    }
    return { visibleTabs: visible, overflowTabs: hidden };
  }, [containerWidth, tabWidths, tabs]);
  const tabKeys = useMemo(
    () => visibleTabs.map((tab) => tab.key),
    [visibleTabs],
  );
  const [activeDragKey, setActiveDragKey] = useState<string | null>(null);
  const activeDragTab = useMemo(
    () => visibleTabs.find((tab) => tab.key === activeDragKey) ?? null,
    [activeDragKey, visibleTabs],
  );
  useEffect(() => {
    if (!overflowOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target instanceof Node ? event.target : null;
      if (
        target &&
        (overflowMenuRef.current?.contains(target) ||
          overflowButtonRef.current?.contains(target))
      )
        return;
      setOverflowOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
    };
  }, [overflowOpen]);
  useLayoutEffect(() => {
    if (!overflowOpen) return;
    const updatePosition = () => {
      const rect = overflowButtonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const menuWidth = 288;
      setOverflowMenuPosition({
        left: Math.max(
          8,
          Math.min(window.innerWidth - menuWidth - 8, rect.right - menuWidth),
        ),
        top: rect.bottom + 4,
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    return () => window.removeEventListener("resize", updatePosition);
  }, [overflowOpen, overflowTabs.length]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 2 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
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
        ref={containerRef}
        data-testid="channel-session-tab-strip"
        className="relative flex h-9 shrink-0 items-center gap-1 overflow-hidden px-3 pb-1 text-[12px]"
      >
        <div
          ref={measureRef}
          aria-hidden="true"
          className="pointer-events-none absolute left-0 top-0 flex h-0 items-center gap-1 overflow-hidden opacity-0"
        >
          {tabs.map((tab) => (
            <MeasuredSessionTab
              key={tab.key}
              tab={tab}
              pending={pendingKey === tab.key}
            />
          ))}
        </div>
        <SortableContext
          items={tabKeys}
          strategy={horizontalListSortingStrategy}
        >
          {visibleTabs.map((tab) => (
            <SortableSessionTab
              key={tab.key}
              tab={tab}
              onSelect={onSelect}
              onFocusSplitPane={onFocusSplitPane}
              onClose={onClose}
              onSplit={onSplit}
              onUnsplitPane={onUnsplitPane}
              onFocusOpenSurface={onFocusOpenSurface}
              onReplaceFocused={onReplaceFocused}
              onMakePrimary={onMakePrimary}
              canRenameSession={canRenameSession}
              onRenameSession={onRenameSession}
              openSurfaceKeys={openSurfaceKeys}
              splitActive={splitActive}
              pending={pendingKey === tab.key}
            />
          ))}
        </SortableContext>
        {overflowTabs.length > 0 && (
          <div className="relative ml-1 shrink-0">
            <button
              ref={overflowButtonRef}
              type="button"
              data-testid="channel-session-tab-overflow-button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                setOverflowOpen((open) => !open);
              }}
              className="flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-[11px] text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
              title={`${overflowTabs.length} hidden ${overflowTabs.length === 1 ? "tab" : "tabs"}`}
            >
              <MoreHorizontal size={14} />
              More
            </button>
            {overflowOpen &&
              overflowMenuPosition &&
              typeof document !== "undefined" &&
              ReactDOM.createPortal(
                <div
                  ref={overflowMenuRef}
                  data-testid="channel-session-tab-overflow-menu"
                  className="fixed z-[10070] max-h-[360px] w-72 overflow-y-auto rounded-md border border-surface-border bg-surface-raised p-1 shadow-lg"
                  style={{
                    left: overflowMenuPosition.left,
                    top: overflowMenuPosition.top,
                  }}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => event.stopPropagation()}
                >
                  {overflowTabs.map((tab) => (
                    <OverflowTabRow
                      key={tab.key}
                      tab={tab}
                      pending={pendingKey === tab.key}
                      onSelect={() => {
                        setOverflowOpen(false);
                        onPromote(tab);
                        onSelect(tab);
                      }}
                      onClose={() => onClose(tab)}
                    />
                  ))}
                </div>,
                document.body,
              )}
          </div>
        )}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeDragTab ? (
          <SessionTabDragGhost
            tab={activeDragTab}
            pending={pendingKey === activeDragTab.key}
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

function MeasuredSessionTab({
  tab,
  pending,
}: {
  tab: ChannelTopTabItem;
  pending: boolean;
}) {
  return (
    <div
      data-measure-tab-key={tab.key}
      className={[
        "flex h-8 shrink-0 items-center gap-1 rounded-md px-1.5 text-left text-[12px]",
        tab.kind === "split" ? "max-w-[360px]" : "max-w-[260px]",
      ].join(" ")}
    >
      <span className="flex h-6 w-4 shrink-0 items-center justify-center">
        <GripVertical size={12} />
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
              ].join(" ")}
            >
              {pane.primary && (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full" />
              )}
              <span className="min-w-0 truncate">{pane.label}</span>
            </span>
          ))}
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {tab.kind === "file" ? (
            <FileText size={12} className="shrink-0" />
          ) : tab.primary ? (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full" />
          ) : null}
          <span className="min-w-0 truncate">{tab.label}</span>
          <span className="hidden shrink-0 text-[10px] uppercase tracking-[0.08em] lg:inline">
            {tab.kind === "file"
              ? tab.splitActive
                ? "Split"
                : "File"
              : tab.primary
                ? "Primary"
                : "Session"}
          </span>
        </div>
      )}
      {pending && <Loader2 size={11} className="shrink-0" />}
      {tab.unreadCount > 0 && (
        <span className="h-4 min-w-4 shrink-0 px-1 text-[9px]">9+</span>
      )}
      <span className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
        <X size={12} />
      </span>
    </div>
  );
}

function OverflowTabRow({
  tab,
  pending,
  onSelect,
  onClose,
}: {
  tab: ChannelTopTabItem;
  pending: boolean;
  onSelect: () => void;
  onClose: () => void;
}) {
  const kindLabel =
    tab.kind === "file"
      ? tab.splitActive
        ? "Split file"
        : "File"
      : tab.kind === "split"
        ? "Split"
        : tab.primary
          ? "Primary"
          : tab.kind === "surface" && tab.surface.kind === "scratch"
            ? "Scratch"
            : "Session";
  return (
    <div className="group flex min-w-0 items-center gap-1 rounded-md hover:bg-surface-overlay/60">
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] text-text-muted group-hover:text-text"
      >
        {tab.kind === "file" ? (
          <FileText size={13} className="shrink-0 text-text-dim" />
        ) : tab.primary ? (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" />
        ) : (
          <StickyNote size={13} className="shrink-0 text-text-dim" />
        )}
        <span className="min-w-0 flex-1 truncate">{tab.label}</span>
        <span className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim">
          {kindLabel}
        </span>
        {pending && (
          <Loader2 size={11} className="shrink-0 animate-spin text-accent" />
        )}
        {tab.unreadCount > 0 && (
          <span className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-accent/15 px-1 text-[9px] font-semibold text-accent">
            {tab.unreadCount > 9 ? "9+" : tab.unreadCount}
          </span>
        )}
      </button>
      <button
        type="button"
        aria-label={`Close ${tab.label} tab`}
        onClick={(event) => {
          event.stopPropagation();
          onClose();
        }}
        className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-dim hover:bg-surface-overlay hover:text-text"
      >
        <X size={12} />
      </button>
    </div>
  );
}

interface SortableSessionTabProps {
  tab: ChannelTopTabItem;
  onSelect: (tab: ChannelTopTabItem) => void;
  onFocusSplitPane: (tab: ChannelTopTabItem, paneId: string) => void;
  onClose: (tab: ChannelTopTabItem) => void;
  onSplit: (tab: ChannelTopTabItem) => void;
  onUnsplitPane: (tab: ChannelTopTabItem, paneId: string) => void;
  onFocusOpenSurface: (tab: ChannelTopTabItem) => void;
  onReplaceFocused: (tab: ChannelTopTabItem) => void;
  onMakePrimary: (tab: ChannelTopTabItem) => void;
  canRenameSession: (tab: ChannelTopTabItem) => boolean;
  onRenameSession: (tab: ChannelTopTabItem, title: string) => void;
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
  onUnsplitPane,
  onFocusOpenSurface,
  onReplaceFocused,
  onMakePrimary,
  canRenameSession,
  onRenameSession,
  openSurfaceKeys,
  splitActive,
  pending,
}: SortableSessionTabProps) {
  const [menuPosition, setMenuPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const surfaceOpen =
    tab.kind === "surface" && openSurfaceKeys.includes(surfaceKey(tab.surface));
  const renameable = tab.kind === "surface" && canRenameSession(tab);
  useEffect(() => {
    if (!menuPosition) return;
    const close = (event: PointerEvent) => {
      const target = event.target instanceof Node ? event.target : null;
      if (target && menuRef.current?.contains(target)) return;
      setMenuPosition(null);
      setRenaming(false);
    };
    window.addEventListener("pointerdown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
    };
  }, [menuPosition]);
  useEffect(() => {
    if (!menuPosition || !renaming) return;
    const frame = requestAnimationFrame(() => {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    });
    return () => cancelAnimationFrame(frame);
  }, [menuPosition, renaming]);
  const closeMenu = () => {
    setMenuPosition(null);
    setRenaming(false);
  };
  const confirmMakePrimary = async () => {
    if (tab.kind !== "surface" || tab.surface.kind === "primary") return;
    const confirmed = await confirm(
      `Set "${tab.label}" as the channel primary session?\n\nIntegrations that mirror the channel primary will switch to mirroring this session.`,
      {
        title: "Set channel primary?",
        confirmLabel: "Set primary",
        variant: "warning",
      },
    );
    if (!confirmed) return;
    closeMenu();
    onMakePrimary(tab);
  };
  const commitRename = () => {
    const title = renameDraft.trim();
    if (!renameable || !title) return;
    onRenameSession(tab, title);
    closeMenu();
  };
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
          ? "bg-surface-overlay/60 text-text"
          : "text-text-muted hover:bg-surface-overlay/45 hover:text-text",
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
    >
      <span
        aria-hidden="true"
        className="flex h-6 w-4 shrink-0 cursor-grab items-center justify-center rounded text-text-dim/40 opacity-0 transition-colors group-hover:bg-surface-overlay group-hover:text-text group-hover:opacity-100 group-focus-within:opacity-100 group-active:cursor-grabbing"
        {...listeners}
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
                pane.focused
                  ? "bg-surface-overlay/80 text-text"
                  : "bg-surface/60 text-text-muted hover:bg-surface-overlay/70 hover:text-text",
              ].join(" ")}
            >
              {pane.primary && (
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80"
                  aria-hidden="true"
                />
              )}
              <span className="min-w-0 truncate">{pane.label}</span>
            </button>
          ))}
        </div>
      ) : tab.kind === "file" ? (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <FileText
            size={12}
            className="shrink-0 text-text-dim"
            aria-hidden="true"
          />
          <span className="min-w-0 truncate">{tab.label}</span>
          <span className="hidden shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim lg:inline">
            {tab.splitActive ? "Split" : "File"}
          </span>
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {tab.primary && (
            <span
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80"
              aria-hidden="true"
            />
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
      {pending && (
        <Loader2
          size={11}
          className="shrink-0 animate-spin text-accent"
          aria-hidden="true"
        />
      )}
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
          tab.active ? "bg-accent/70" : "bg-transparent",
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
        className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-dim opacity-0 transition-colors hover:bg-surface-overlay hover:text-text group-hover:opacity-100 focus-visible:opacity-100"
      >
        <X size={12} />
      </button>
      {menuPosition &&
        typeof document !== "undefined" &&
        ReactDOM.createPortal(
          <div
            ref={menuRef}
            data-testid="channel-session-tab-menu"
            className="fixed z-40 w-64 rounded-md border border-surface-border bg-surface-raised p-1 shadow-lg"
            style={{ left: menuPosition.x, top: menuPosition.y }}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
          >
            {renaming ? (
              <form
                className="flex flex-col gap-2 p-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  commitRename();
                }}
              >
                <label
                  className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80"
                  htmlFor={`rename-${tab.key}`}
                >
                  Rename session
                </label>
                <input
                  id={`rename-${tab.key}`}
                  ref={renameInputRef}
                  data-testid="channel-session-tab-rename-input"
                  value={renameDraft}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setRenaming(false);
                    }
                  }}
                  className="h-8 rounded-md border border-surface-border bg-surface px-2 text-[12px] text-text outline-none focus:border-accent"
                />
                <div className="flex items-center justify-end gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setRenaming(false);
                    }}
                    className="rounded px-2 py-1.5 text-[12px] text-text-dim hover:bg-surface-overlay hover:text-text"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!renameDraft.trim()}
                    className="rounded bg-accent/15 px-2 py-1.5 text-[12px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
              </form>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    onSelect(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                >
                  {tab.kind === "split" ? "Open split" : "Open"}
                </button>
                {tab.kind === "split" ? (
                  <>
                    <div className="my-1 h-px bg-surface-border/60" />
                    <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">
                      Unsplit to
                    </div>
                    {tab.panes.map((pane) => (
                      <button
                        key={pane.id}
                        type="button"
                        onClick={() => {
                          closeMenu();
                          onUnsplitPane(tab, pane.id);
                        }}
                        className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                      >
                        {pane.label}
                      </button>
                    ))}
                  </>
                ) : tab.kind === "file" ? (
                  <>
                    <button
                      type="button"
                      disabled={tab.splitActive}
                      onClick={() => {
                        closeMenu();
                        onSplit(tab);
                      }}
                      className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:text-text-dim disabled:opacity-50"
                    >
                      {tab.splitActive ? "Already split" : "Split right"}
                    </button>
                  </>
                ) : (
                  <>
                    {surfaceOpen ? (
                      <button
                        type="button"
                        disabled={!splitActive}
                        onClick={() => {
                          closeMenu();
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
                          closeMenu();
                          onSplit(tab);
                        }}
                        className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                      >
                        Split right
                      </button>
                    )}
                    {renameable && (
                      <button
                        type="button"
                        onClick={() => {
                          setRenameDraft(tab.label);
                          setRenaming(true);
                        }}
                        className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                      >
                        Rename session
                      </button>
                    )}
                    {splitActive && !surfaceOpen && (
                      <button
                        type="button"
                        onClick={() => {
                          closeMenu();
                          onReplaceFocused(tab);
                        }}
                        className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
                      >
                        Replace focused split
                      </button>
                    )}
                    {tab.kind === "surface" &&
                      tab.surface.kind !== "primary" && (
                        <button
                          type="button"
                          onClick={() => {
                            void confirmMakePrimary();
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
                    closeMenu();
                    onClose(tab);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-danger hover:bg-danger/10"
                >
                  Close tab
                </button>
              </>
            )}
          </div>,
          document.body,
        )}
      <ConfirmDialogSlot />
    </div>
  );
}

function SessionTabDragGhost({
  tab,
  pending,
}: {
  tab: ChannelTopTabItem;
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
                pane.focused
                  ? "bg-accent/[0.10] text-text"
                  : "bg-surface/60 text-text-muted",
              ].join(" ")}
            >
              {pane.primary && (
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80"
                  aria-hidden="true"
                />
              )}
              <span className="min-w-0 truncate">{pane.label}</span>
            </span>
          ))}
        </div>
      ) : tab.kind === "file" ? (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <FileText
            size={12}
            className="shrink-0 text-text-dim"
            aria-hidden="true"
          />
          <span className="min-w-0 truncate">{tab.label}</span>
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {tab.primary && (
            <span
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80"
              aria-hidden="true"
            />
          )}
          <span className="min-w-0 truncate">{tab.label}</span>
        </div>
      )}
      {pending && (
        <Loader2
          size={11}
          className="shrink-0 animate-spin text-accent"
          aria-hidden="true"
        />
      )}
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
  onActivateSurface: (
    surface: ChannelSessionSurface,
    intent: ChannelSessionActivationIntent,
  ) => void;
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
  const {
    data: channelSessions,
    isLoading,
    error,
  } = useChannelSessionCatalog(channelId);

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
      className="flex min-h-0 flex-1 items-stretch justify-center overflow-hidden bg-surface px-6 py-6"
    >
      <div className="flex min-h-0 w-full max-w-2xl flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-text">
              Choose a session
            </div>
            <div className="mt-1 text-[12px] text-text-dim">
              Closed tabs stay in history. Pick a recent session to bring it
              back.
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
        <div className="min-h-0 flex-1 overflow-y-auto rounded-md bg-surface-raised/35">
          {isLoading && (
            <div className="px-4 py-8 text-sm text-text-dim">
              Loading sessions...
            </div>
          )}
          {error && (
            <div className="px-4 py-8 text-sm text-danger">
              {error instanceof Error
                ? error.message
                : "Failed to load sessions."}
            </div>
          )}
          {!isLoading && !error && entries.length === 0 && (
            <div className="px-4 py-8 text-sm text-text-dim">
              No sessions matched that search.
            </div>
          )}
          {!isLoading &&
            !error &&
            groups.map((group) => (
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
                      <span className="block truncate text-[13px] font-medium text-text">
                        {entry.label}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-text-dim">
                        {entry.meta}
                      </span>
                      {entry.matches && entry.matches.length > 0 && (
                        <span className="mt-1 block space-y-1">
                          {entry.matches.slice(0, 2).map((match, idx) => (
                            <span
                              key={`${match.kind}:${match.message_id ?? match.section_id ?? idx}`}
                              className="block truncate text-[11px] text-text-muted"
                            >
                              {match.kind === "section" ? "Section" : "Message"}
                              : {match.preview}
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
            <div className="px-4 py-2 text-[11px] text-text-dim">
              Searching message history...
            </div>
          )}
          {deepSearchError && (
            <div className="px-4 py-2 text-[11px] text-danger">
              {deepSearchError instanceof Error
                ? deepSearchError.message
                : "Deep search failed."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
