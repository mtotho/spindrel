import { useState } from "react";
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { Activity, AlertTriangle, Bot, Box, Clock, Eye, ExternalLink, Hash, History, Info, LayoutList, MapPin, MessageCircle, PanelRightOpen, Radar, Search, Settings2, Sparkles, X } from "lucide-react";
import type { AttentionTargetKind, WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import { activeAttentionItems, getAttentionWorkflowState } from "./SpatialAttentionModel";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";
import { ObjectStatusPill, mapCueIntent, mapCueRank, mapStateMeta } from "./SpatialObjectStatus";
import { buildSpatialObjectBrief, formatSignalTime } from "./SpatialObjectBrief";
import { openTraceInspector } from "../../stores/traceInspector";
import { attentionDeckHref } from "../../lib/hubRoutes";

export interface StarboardObjectItem {
  id: string;
  label: string;
  kind: "channel" | "widget" | "bot" | "landmark";
  subtitle?: string;
  worldX: number;
  worldY: number;
  worldW: number;
  worldH: number;
  distance: number;
  onSelect: () => void;
  onDoubleClick?: () => void;
  workState?: WorkspaceMapObjectState | null;
  actions: StarboardObjectAction[];
}

export interface StarboardObjectAction {
  label: string;
  icon?: "jump" | "open" | "chat" | "settings" | "activate";
  onSelect: () => void;
  disabled?: boolean;
}

export type StarboardStation = "objects";

interface UsageDensityChromeProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  objects: StarboardObjectItem[];
  attentionItems: WorkspaceAttentionItem[];
  selectedAttentionId: string | null;
  onSelectAttention: (item: WorkspaceAttentionItem | null) => void;
  onReplyAttention?: (item: WorkspaceAttentionItem) => void;
  navigate?: (to: string, options?: any) => void;
  selectedObject?: StarboardObjectItem | null;
}

const STARBOARD_TAB_KEY = "spatial.starboard.activeTab";
const STARBOARD_DEFAULT_MIGRATION_KEY = "spatial.starboard.mapBriefDefault.v1";
const STARBOARD_WIDTH_KEY = "spatial.starboard.width";
const DEFAULT_STARBOARD_WIDTH = 600;
const MIN_STARBOARD_WIDTH = 420;

const KIND_LABEL: Record<StarboardObjectItem["kind"], string> = {
  channel: "Channel",
  widget: "Widget",
  bot: "Bot",
  landmark: "Landmark",
};

type ObjectGroup = {
  id: "investigate" | "next" | "recent" | "quiet";
  label: string;
  items: StarboardObjectItem[];
};

export function loadStarboardStation(): StarboardStation {
  try {
    window.localStorage.setItem(STARBOARD_DEFAULT_MIGRATION_KEY, "done");
    window.localStorage.setItem(STARBOARD_TAB_KEY, "objects");
    return "objects";
  } catch {
    return "objects";
  }
}

export function UsageDensityChrome({
  open,
  onOpenChange,
  objects,
  attentionItems,
  selectedAttentionId,
  onSelectAttention,
  navigate,
  selectedObject,
}: UsageDensityChromeProps) {
  const [objectQuery, setObjectQuery] = useState("");
  const [objectMenu, setObjectMenu] = useState<{
    x: number;
    y: number;
    item: StarboardObjectItem;
  } | null>(null);
  const [panelWidth, setPanelWidth] = useState(() => loadStarboardWidth());
  const normalizedQuery = objectQuery.trim().toLowerCase();
  const visibleObjects = objects.filter((item) => {
    if (!normalizedQuery) return true;
    return `${item.label} ${item.subtitle ?? ""} ${item.workState?.primary_signal ?? ""} ${KIND_LABEL[item.kind]}`.toLowerCase().includes(normalizedQuery);
  });
  const objectGroups = buildObjectGroups(visibleObjects, selectedObject);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = panelWidth;
    const maxWidth = Math.max(MIN_STARBOARD_WIDTH, window.innerWidth - 24);
    let latest = startWidth;
    const move = (moveEvent: PointerEvent) => {
      latest = clampStarboardWidth(startWidth + startX - moveEvent.clientX, maxWidth);
      setPanelWidth(latest);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      persistStarboardWidth(latest);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const handleObjectClick = (item: StarboardObjectItem) => {
    item.onSelect();
  };

  const handleObjectDoubleClick = (item: StarboardObjectItem) => {
    if (!item.onDoubleClick) return;
    item.onDoubleClick();
  };

  return (
    <div
      className="flex flex-row items-stretch gap-2"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        aria-expanded={open}
        aria-label="Open Starboard"
        title="Open Starboard"
        className={`inline-flex h-10 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors ${
          open
            ? "bg-accent/[0.08] text-accent"
            : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
        }`}
      >
        <PanelRightOpen size={16} />
        <span className="hidden sm:inline">Starboard</span>
      </button>
      {open && (
        <aside
          data-starboard-panel="true"
          className="fixed bottom-0 right-0 top-0 z-[65] flex max-w-[calc(100vw-1rem)] flex-col border-l border-surface-border bg-surface-raised/95 text-sm text-text backdrop-blur"
          style={{ width: panelWidth }}
          onPointerDown={(event) => event.stopPropagation()}
          onContextMenu={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          onWheelCapture={(event) => {
            event.stopPropagation();
          }}
        >
          <div
            className="absolute bottom-0 left-0 top-0 w-1 cursor-ew-resize bg-transparent transition-colors hover:bg-accent/25"
            onPointerDown={startResize}
            title="Resize Starboard"
          />
          <div className="flex items-center justify-between px-2.5 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-1.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
                <LayoutList size={15} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">Starboard</span>
                <span className="block truncate text-base font-semibold text-text">
                  {selectedObject ? `${KIND_LABEL[selectedObject.kind]} inspector` : "Object inspector"}
                </span>
              </span>
            </div>
            <button
              type="button"
              className="rounded-md p-2 text-text-muted hover:bg-surface-overlay/60 hover:text-text"
              onClick={() => onOpenChange(false)}
              aria-label="Close Starboard"
              title="Close"
            >
              <X size={16} />
            </button>
          </div>

          <div data-testid="starboard-scroll-body" className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3 pt-2">
                <div data-testid="starboard-map-brief">
                  {selectedObject && (
                    <SelectedObjectInspector
                      item={selectedObject}
                      attentionItems={attentionItems ?? []}
                      selectedAttentionId={selectedAttentionId}
                      onOpenAttentionWarning={(id) => {
                        const item = (attentionItems ?? []).find((entry) => entry.id === id);
                        if (item) onSelectAttention(item);
                        navigate?.(attentionDeckHref({ itemId: id }));
                      }}
                      navigate={navigate}
                    />
                  )}
                  <div className="mb-3 px-1">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">{selectedObject ? "Related Objects" : "Map Objects"}</div>
                      <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{visibleObjects.length}</span>
                    </div>
                    <div className="mt-1 text-sm text-text-muted">
                      {selectedObject ? "Best next steps first, then nearby quiet objects." : "Objects grouped by what the map thinks is worth doing next."}
                    </div>
                  </div>
                  <label className="mb-3 flex items-center gap-2 rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text">
                    <Search size={15} className="text-text-dim" />
                    <input
                      value={objectQuery}
                      onChange={(event) => setObjectQuery(event.target.value)}
                      className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-text-dim"
                      placeholder="Search objects"
                    />
                  </label>
                  <div className="space-y-3">
                    {objectGroups.map((group) => (
                      <ObjectListGroup
                        key={group.id}
                        group={group}
                        selectedId={selectedObject?.id ?? null}
                        onClick={handleObjectClick}
                        onDoubleClick={handleObjectDoubleClick}
                        onContextMenu={(event, item) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setObjectMenu({ x: event.clientX, y: event.clientY, item });
                        }}
                      />
                    ))}
                    {!objectGroups.length && (
                      <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-6 text-center text-sm text-text-dim">
                        No positioned objects match.
                      </div>
                    )}
                  </div>
                </div>
          </div>
          {objectMenu && (
            <ObjectContextMenu
              x={objectMenu.x}
              y={objectMenu.y}
              item={objectMenu.item}
              onClose={() => setObjectMenu(null)}
            />
          )}
        </aside>
      )}
    </div>
  );
}

function loadStarboardWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(STARBOARD_WIDTH_KEY));
    return clampStarboardWidth(stored || DEFAULT_STARBOARD_WIDTH);
  } catch {
    return DEFAULT_STARBOARD_WIDTH;
  }
}

function persistStarboardWidth(width: number) {
  try {
    window.localStorage.setItem(STARBOARD_WIDTH_KEY, String(Math.round(width)));
  } catch {
    /* storage disabled */
  }
}

function clampStarboardWidth(width: number, maxWidth = Math.max(MIN_STARBOARD_WIDTH, window.innerWidth - 24)): number {
  return Math.round(Math.min(maxWidth, Math.max(MIN_STARBOARD_WIDTH, width)));
}

function buildObjectGroups(objects: StarboardObjectItem[], selectedObject?: StarboardObjectItem | null): ObjectGroup[] {
  const selectedId = selectedObject?.id ?? null;
  const candidates = objects
    .filter((item) => item.id !== selectedId)
    .slice()
    .sort((a, b) => cuePriority(b) - cuePriority(a) || a.distance - b.distance || a.label.localeCompare(b.label));
  const investigate = candidates.filter((item) => mapCueIntent(item.workState) === "investigate");
  const next = candidates.filter((item) => mapCueIntent(item.workState) === "next");
  const recent = candidates.filter((item) => mapCueIntent(item.workState) === "recent");
  const quiet = candidates.filter((item) => mapCueIntent(item.workState) === "quiet").slice(0, selectedObject ? 10 : 8);
  const groups: ObjectGroup[] = [];
  if (investigate.length) groups.push({ id: "investigate", label: "Investigate", items: investigate });
  if (next.length) groups.push({ id: "next", label: "Next up", items: next });
  if (recent.length) groups.push({ id: "recent", label: "Recently changed", items: recent });
  if (quiet.length) groups.push({ id: "quiet", label: selectedObject ? "Nearby quiet" : "Quiet nearby", items: quiet });
  return groups;
}

function cuePriority(item: StarboardObjectItem): number {
  return (mapCueRank(item.workState) * 1000) + (item.workState?.cue?.priority ?? 0);
}

function objectNeedsAttention(item: StarboardObjectItem): boolean {
  if (mapCueIntent(item.workState) === "investigate") return true;
  const status = item.workState?.status;
  return status === "error" || status === "warning" || item.workState?.severity === "critical" || item.workState?.severity === "error" || item.workState?.severity === "warning";
}

function ObjectListGroup({
  group,
  selectedId,
  onClick,
  onDoubleClick,
  onContextMenu,
}: {
  group: ObjectGroup;
  selectedId: string | null;
  onClick: (item: StarboardObjectItem) => void;
  onDoubleClick: (item: StarboardObjectItem) => void;
  onContextMenu: (event: ReactPointerEvent<HTMLButtonElement> | ReactMouseEvent<HTMLButtonElement>, item: StarboardObjectItem) => void;
}) {
  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between gap-3 px-1">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">{group.label}</div>
        <span className="text-[11px] text-text-dim">{group.items.length}</span>
      </div>
      <div className="space-y-1">
        {group.items.map((item) => {
          const selected = item.id === selectedId;
          const needsAttention = objectNeedsAttention(item);
          return (
            <button
              key={item.id}
              type="button"
              data-testid="map-brief-object-row"
              data-starboard-object-id={item.id}
              onClick={() => onClick(item)}
              onDoubleClick={() => onDoubleClick(item)}
              onContextMenu={(event) => onContextMenu(event, item)}
              className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors duration-100 ${
                selected
                  ? "bg-accent/[0.08] text-accent"
                  : needsAttention
                    ? "bg-surface-raised/30 hover:bg-surface-overlay/55"
                    : "hover:bg-surface-overlay/55"
              }`}
            >
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${kindTone(item.kind)}`}>
                {kindIcon(item.kind)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-text">{item.label}</span>
                  <ObjectStatusPill state={item.workState} compact />
                  <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                    {KIND_LABEL[item.kind]}
                  </span>
                </span>
                <span className="block truncate text-xs text-text-dim">{item.subtitle ?? mapStateMeta(item.workState) ?? KIND_LABEL[item.kind]}</span>
              </span>
              <span className="shrink-0 text-xs text-text-dim">{formatDistance(item.distance)}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function attentionPrimaryActionLabel(item: WorkspaceAttentionItem | null): string {
  if (!item) return "Review signal";
  return getAttentionWorkflowState(item) === "operator_review" ? "Review finding" : "Review item";
}

function SelectedObjectInspector({
  item,
  attentionItems,
  selectedAttentionId,
  onOpenAttentionWarning,
  navigate,
}: {
  item: StarboardObjectItem;
  attentionItems: WorkspaceAttentionItem[];
  selectedAttentionId?: string | null;
  onOpenAttentionWarning: (id: string) => void;
  navigate?: (to: string, options?: any) => void;
}) {
  const defaultPrimary = item.actions.find((action) => action.icon !== "jump") ?? item.actions[0];
  const state = item.workState;
  const brief = buildSpatialObjectBrief(state);
  const target = attentionTargetForObject(item);
  const targetAttentionItems = findActiveAttentionItemsForObject(item, attentionItems);
  const firstTargetAttention = targetAttentionItems[0] ?? null;
  const hasOperatorReview = targetAttentionItems.some((entry) => getAttentionWorkflowState(entry) === "operator_review");
  const primary: StarboardObjectAction | undefined = firstTargetAttention
    ? {
        label: attentionPrimaryActionLabel(firstTargetAttention),
        icon: "open",
        onSelect: () => onOpenAttentionWarning(firstTargetAttention.id),
      }
    : defaultPrimary;
  const usefulActions = item.actions.filter((action) => action !== defaultPrimary).slice(0, 4);
  const tone = brief?.tone ?? "muted";
  const toneClass = selectedInspectorToneClass(tone);
  return (
    <section
      data-testid="map-brief-selected-object"
      data-starboard-object-id={item.id}
      data-brief-tone={tone}
      className={`mb-4 rounded-md px-3 py-3 ${toneClass}`}
    >
      <div className="flex items-start gap-2.5">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${kindTone(item.kind)}`}>
          {kindIcon(item.kind)}
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">Selected {KIND_LABEL[item.kind]}</div>
          <div className="truncate text-base font-semibold text-text">{item.label}</div>
        </div>
        {primary && (
          <button
            type="button"
            data-testid="map-brief-action"
            data-action-label={primary.label}
            disabled={primary.disabled}
            className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md bg-accent/[0.08] px-2 text-xs font-medium text-accent hover:bg-accent/[0.12] disabled:cursor-not-allowed disabled:text-text-dim"
            onClick={primary.onSelect}
          >
            {actionIcon(primary.icon)}
            {primary.label}
          </button>
        )}
      </div>
      <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
        <ObjectStatusPill state={item.workState} compact />
        <span className="min-w-0 truncate rounded-full bg-surface-overlay/50 px-2 py-0.5 text-[11px] text-text-dim">
          {brief?.headline ?? item.subtitle ?? KIND_LABEL[item.kind]}
        </span>
        <SelectedObjectMetaChips brief={brief} />
      </div>
      <div className="mt-2.5 text-sm leading-relaxed text-text-muted">
        {brief?.summary ?? "No live map state is attached to this object yet."}
      </div>
      {target && targetAttentionItems.length > 0 && (
        <div
          data-testid="map-brief-attention-actions"
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-overlay/25 px-2.5 py-2"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-xs font-medium text-text">
              {hasOperatorReview ? <Sparkles size={13} className="text-accent" /> : <AlertTriangle size={13} className="text-danger" />}
              <span>
                {hasOperatorReview
                  ? `${targetAttentionItems.length} operator-reviewed finding${targetAttentionItems.length === 1 ? "" : "s"}`
                  : `${targetAttentionItems.length} untriaged attention item${targetAttentionItems.length === 1 ? "" : "s"}`}
              </span>
            </div>
            <div className="mt-0.5 truncate text-xs text-text-dim">
              {firstTargetAttention?.title ?? "Attention is active on this target."}
            </div>
          </div>
        </div>
      )}
      {(brief || usefulActions.length > 0) && (
        <div className="mt-3 grid gap-2.5">
          {brief && (
            <>
              {!!brief.sourceLines.length && (
                <InspectorSection icon={<Info size={13} />} title="What this is">
                  {brief.sourceLines.map((line) => (
                    <div key={line} className="truncate text-text-muted">{line}</div>
                  ))}
                </InspectorSection>
              )}
              {brief.next && (
                <InspectorSection icon={<Clock size={13} />} title="Next">
                  <SignalLine signal={brief.next} navigate={navigate} />
                </InspectorSection>
              )}
              {!!brief.warnings.length && (
                <InspectorSection icon={<AlertTriangle size={13} />} title="Warnings">
                  {brief.warnings.map((signal, index) => (
                    <SignalLine
                      key={`${signal.kind}-${signal.id ?? index}`}
                      signal={signal}
                      danger
                      highlighted={Boolean(signal.id && signal.id === selectedAttentionId)}
                      onOpenAttentionWarning={onOpenAttentionWarning}
                      navigate={navigate}
                    />
                  ))}
                </InspectorSection>
              )}
              {!!brief.recent.length && (
                <InspectorSection icon={<History size={13} />} title="Recent">
                  {brief.recent.map((signal, index) => (
                    <SignalLine
                      key={`${signal.kind}-${signal.id ?? index}`}
                      signal={signal}
                      onOpenAttentionWarning={onOpenAttentionWarning}
                      navigate={navigate}
                    />
                  ))}
                </InspectorSection>
              )}
            </>
          )}
          {!!usefulActions.length && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {usefulActions.map((action) => (
                <button
                  key={action.label}
                  type="button"
                  data-testid="map-brief-action"
                  data-action-label={action.label}
                  disabled={action.disabled}
                  onClick={action.onSelect}
                  className="inline-flex min-h-7 items-center gap-1.5 rounded-md bg-surface-overlay/50 px-2 text-xs font-medium text-text-muted hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:text-text-dim/50"
                >
                  {actionIcon(action.icon)}
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function selectedInspectorToneClass(tone: "danger" | "warning" | "active" | "muted"): string {
  if (tone === "danger") return "bg-surface-overlay/20";
  if (tone === "warning") return "bg-surface-overlay/20";
  if (tone === "active") return "bg-surface-overlay/18";
  return "bg-surface-overlay/16";
}

function SelectedObjectMetaChips({ brief }: { brief: ReturnType<typeof buildSpatialObjectBrief> }) {
  if (!brief) return null;
  const chips = [
    brief.next ? "next" : null,
    brief.warnings.length ? `${brief.warnings.length} warning${brief.warnings.length === 1 ? "" : "s"}` : null,
    brief.recent.length ? `${brief.recent.length} recent` : null,
  ].filter(Boolean);
  if (!chips.length) return null;
  return (
    <>
      {chips.map((chip) => (
        <span key={chip} className="rounded-full bg-surface-overlay/40 px-2 py-0.5 text-[11px] text-text-dim">
          {chip}
        </span>
      ))}
    </>
  );
}

type AttentionObjectTarget = {
  kind: Extract<AttentionTargetKind, "channel" | "bot" | "widget">;
  targetId: string;
  channelId?: string | null;
};

function sourceString(state: WorkspaceMapObjectState | null | undefined, key: string): string | null {
  const value = state?.source?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function attentionTargetForObject(item: StarboardObjectItem): AttentionObjectTarget | null {
  const state = item.workState;
  if (!state) return null;
  if (item.kind === "channel") {
    const targetId = state.target_id || sourceString(state, "channel_id");
    if (!targetId) return null;
    return { kind: "channel", targetId, channelId: sourceString(state, "channel_id") ?? targetId };
  }
  if (item.kind === "bot") {
    const targetId = state.target_id || sourceString(state, "bot_id");
    if (!targetId) return null;
    return { kind: "bot", targetId };
  }
  if (item.kind === "widget") {
    const targetId = state.target_id || sourceString(state, "widget_pin_id");
    if (!targetId) return null;
    return { kind: "widget", targetId, channelId: sourceString(state, "source_channel_id") };
  }
  return null;
}

function findActiveAttentionItemsForObject(item: StarboardObjectItem, items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  const target = attentionTargetForObject(item);
  const attentionWarningIds = new Set(
    (item.workState?.warnings ?? [])
      .filter((signal) => signal.kind === "attention" && signal.id)
      .map((signal) => signal.id!),
  );
  const targetMatches = (entry: WorkspaceAttentionItem) => {
    if (attentionWarningIds.has(entry.id)) return true;
    if (!target) return false;
    if (entry.target_kind === target.kind && entry.target_id === target.targetId) return true;
    if (target.kind === "channel" && (entry.channel_id === target.targetId || entry.channel_id === target.channelId)) return true;
    if (target.channelId && entry.channel_id === target.channelId && entry.target_id === target.targetId) return true;
    return false;
  };
  return activeAttentionItems(items).filter(targetMatches).sort((a, b) => {
    const aReview = getAttentionWorkflowState(a) === "operator_review" ? 1 : 0;
    const bReview = getAttentionWorkflowState(b) === "operator_review" ? 1 : 0;
    return bReview - aReview;
  });
}

function InspectorSection({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 py-1">
      <div className="pt-0.5 text-text-dim" aria-hidden>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-text-dim">
          {title}
        </div>
        <div className="grid gap-1 text-xs">{children}</div>
      </div>
    </section>
  );
}

function SignalLine({
  signal,
  danger = false,
  highlighted = false,
  onOpenAttentionWarning,
  navigate,
}: {
  signal: NonNullable<WorkspaceMapObjectState["next"]> | WorkspaceMapObjectState["recent"][number];
  danger?: boolean;
  highlighted?: boolean;
  onOpenAttentionWarning?: (id: string) => void;
  navigate?: (to: string, options?: any) => void;
}) {
  const when = formatSignalTime(signal);
  const action = signalAction(signal, onOpenAttentionWarning, navigate);
  const content = (
    <>
      <div className={`truncate font-medium ${danger ? "text-danger" : "text-text"}`}>{signal.title || signal.kind}</div>
      <div className="truncate text-text-dim">
        {[signal.bot_name, signal.channel_name ? `#${signal.channel_name}` : null, when].filter(Boolean).join(" · ")}
      </div>
      {signal.message || signal.error ? (
        <div className="mt-0.5 line-clamp-2 text-text-muted">{signal.message || signal.error}</div>
      ) : null}
      {action && (
        <div className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-accent">
          {action.icon}
          {action.label}
        </div>
      )}
    </>
  );
  if (action) {
    return (
      <button
        type="button"
        data-testid="map-brief-signal-action"
        data-signal-kind={signal.kind}
        className={`min-w-0 rounded px-2 py-1 text-left transition-colors hover:bg-surface-overlay/50 focus-visible:bg-surface-overlay/50 ${
          highlighted ? "bg-surface-overlay/60" : ""
        }`}
        onClick={action.onSelect}
      >
        {content}
      </button>
    );
  }
  return (
    <div className={`min-w-0 rounded ${highlighted ? "bg-surface-overlay/60 px-2 py-1" : ""}`}>
      {content}
    </div>
  );
}

function signalAction(
  signal: NonNullable<WorkspaceMapObjectState["next"]> | WorkspaceMapObjectState["recent"][number],
  onOpenAttentionWarning?: (id: string) => void,
  navigate?: (to: string, options?: any) => void,
): { label: string; icon: ReactNode; onSelect: () => void } | null {
  if (signal.kind === "attention" && signal.id && onOpenAttentionWarning) {
    return {
      label: "Review signal",
      icon: <ExternalLink size={11} />,
      onSelect: () => onOpenAttentionWarning(signal.id!),
    };
  }
  const correlationId = signal.correlation_id || (signal.kind === "trace" ? signal.id : null);
  if (correlationId) {
    return {
      label: "Open trace",
      icon: <Activity size={11} />,
      onSelect: () => openTraceInspector({
        correlationId,
        title: signal.title || "Trace",
        subtitle: signal.channel_name ? `#${signal.channel_name}` : signal.bot_name ?? undefined,
      }),
    };
  }
  const taskId = signal.task_id || (signal.kind === "task" ? signal.id : null);
  if (taskId && navigate) {
    return {
      label: "Open automation",
      icon: <ExternalLink size={11} />,
      onSelect: () => navigate(`/admin/automations/${taskId}`),
    };
  }
  return null;
}

function ObjectContextMenu({ x, y, item, onClose }: { x: number; y: number; item: StarboardObjectItem; onClose: () => void }) {
  const left = Math.min(x, window.innerWidth - 230);
  const top = Math.min(y, window.innerHeight - Math.max(64, item.actions.length * 34 + 12));
  return (
    <div
      className="fixed z-[80] min-w-[220px] rounded-md border border-surface-border bg-surface-raised/95 py-1 text-xs text-text backdrop-blur"
      style={{ left, top }}
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
    >
      {item.actions.length === 0 ? (
        <div className="px-3 py-2 text-text-dim">No applicable actions</div>
      ) : item.actions.map((action) => (
        <button
          key={action.label}
          type="button"
          disabled={action.disabled}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-text-muted hover:bg-surface-overlay/60 hover:text-text disabled:cursor-not-allowed disabled:text-text-dim/50"
          onClick={() => {
            if (action.disabled) return;
            action.onSelect();
            onClose();
          }}
        >
          <span className="flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>{actionIcon(action.icon)}</span>
          <span className="truncate">{action.label}</span>
        </button>
      ))}
    </div>
  );
}

function actionIcon(icon: StarboardObjectAction["icon"]) {
  if (icon === "open") return <ExternalLink size={14} />;
  if (icon === "chat") return <MessageCircle size={14} />;
  if (icon === "settings") return <Settings2 size={14} />;
  if (icon === "activate") return <Eye size={14} />;
  return <MapPin size={14} />;
}

function formatDistance(distance: number): string {
  if (!Number.isFinite(distance)) return "";
  if (distance < 1000) return `${Math.round(distance)}`;
  return `${(distance / 1000).toFixed(distance < 10_000 ? 1 : 0)}k`;
}

function kindTone(kind: StarboardObjectItem["kind"]): string {
  if (kind === "channel") return "bg-accent/10 text-accent";
  if (kind === "widget") return "bg-warning/10 text-warning-muted";
  if (kind === "bot") return "bg-success/10 text-success";
  return "bg-surface-overlay text-text-muted";
}

function kindIcon(kind: StarboardObjectItem["kind"]) {
  if (kind === "channel") return <Hash size={15} />;
  if (kind === "widget") return <Box size={15} />;
  if (kind === "bot") return <Bot size={15} />;
  if (kind === "landmark") return <Radar size={15} />;
  return <MapPin size={15} />;
}
