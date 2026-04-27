import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Bot, Box, ChevronDown, Command, Eye, ExternalLink, Hash, LayoutList, MapPin, MapPinned, MessageCircle, PanelRightOpen, Plus, Radar, Search, Settings2, X } from "lucide-react";
import type { DensityWindow } from "./UsageDensityLayer";
import type { DensityIntensity } from "./spatialGeometry";
import { AttentionHubContent } from "./SpatialAttentionLayer";
import { CanvasLibraryContent } from "./CanvasLibrarySheet";
import type { WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import SummaryPanel from "../system-health/SummaryPanel";

export interface StarboardObjectItem {
  id: string;
  label: string;
  kind: "channel" | "widget" | "bot" | "landmark";
  subtitle?: string;
  worldX: number;
  worldY: number;
  distance: number;
  onSelect: () => void;
  onDoubleClick?: () => void;
  actions: StarboardObjectAction[];
}

export interface StarboardObjectAction {
  label: string;
  icon?: "jump" | "open" | "chat" | "settings" | "activate";
  onSelect: () => void;
  disabled?: boolean;
}

export type StarboardStation = "attention" | "launch" | "health" | "objects" | "controls";

interface UsageDensityChromeProps {
  open: boolean;
  station: StarboardStation;
  onOpenChange: (open: boolean) => void;
  onStationChange: (station: StarboardStation) => void;
  intensity: DensityIntensity;
  onCycleIntensity: () => void;
  window: DensityWindow;
  onWindowChange: (w: DensityWindow) => void;
  compare: boolean;
  onCompareChange: (c: boolean) => void;
  animate: boolean;
  onAnimateChange: (a: boolean) => void;
  connectionsEnabled: boolean;
  onConnectionsToggle: () => void;
  botsVisible: boolean;
  onBotsVisibleChange: (visible: boolean) => void;
  botsReduced: boolean;
  onBotsReducedChange: (reduced: boolean) => void;
  landmarkBeaconsVisible: boolean;
  onLandmarkBeaconsVisibleChange: (visible: boolean) => void;
  attentionSignalsVisible: boolean;
  onAttentionSignalsVisibleChange: (visible: boolean) => void;
  onOpenPalette: () => void;
  objects: StarboardObjectItem[];
  attentionItems: WorkspaceAttentionItem[];
  selectedAttentionId: string | null;
  onSelectAttention: (item: WorkspaceAttentionItem | null) => void;
  onReplyAttention?: (item: WorkspaceAttentionItem) => void;
  launchWorldCenter: { x: number; y: number } | null;
}

const WINDOWS: DensityWindow[] = ["24h", "7d", "30d"];

const INTENSITY_LABEL: Record<DensityIntensity, string> = {
  off: "Activity off",
  subtle: "Activity",
  bold: "Activity bold",
};

const INTENSITY_HINT: Record<DensityIntensity, string> = {
  off: "Activity halos hidden — click to enable",
  subtle: "Subtle activity halos — click to brighten",
  bold: "Bold activity halos — click to hide",
};

const STARBOARD_TAB_KEY = "spatial.starboard.activeTab";

const KIND_LABEL: Record<StarboardObjectItem["kind"], string> = {
  channel: "Channel",
  widget: "Widget",
  bot: "Bot",
  landmark: "Landmark",
};

const STATIONS: Array<{ id: StarboardStation; label: string; eyebrow: string; icon: ReactNode }> = [
  { id: "attention", label: "Attention", eyebrow: "Issues and assignments", icon: <Radar size={15} /> },
  { id: "launch", label: "Launch Bay", eyebrow: "Add to canvas", icon: <Plus size={15} /> },
  { id: "health", label: "Daily Health", eyebrow: "Server rollup", icon: <Activity size={15} /> },
  { id: "objects", label: "Objects", eyebrow: "Map entities", icon: <LayoutList size={15} /> },
  { id: "controls", label: "Controls", eyebrow: "Canvas behavior", icon: <Settings2 size={15} /> },
];

export function loadStarboardStation(): StarboardStation {
  try {
    const stored = window.localStorage.getItem(STARBOARD_TAB_KEY);
    return stored === "objects" || stored === "controls" || stored === "attention" || stored === "launch" || stored === "health" ? stored : "attention";
  } catch {
    return "attention";
  }
}

/** Three-dot intensity indicator inside the button — visualizes off/subtle/bold. */
function IntensityPips({ intensity }: { intensity: DensityIntensity }) {
  const filled = intensity === "off" ? 0 : intensity === "subtle" ? 1 : 2;
  return (
    <span className="inline-flex flex-row items-center gap-[3px] mr-1">
      {[0, 1].map((i) => (
        <span
          key={i}
          className="block rounded-full"
          style={{
            width: 5,
            height: 5,
            background:
              i < filled
                ? "currentColor"
                : "rgb(var(--color-text) / 0.25)",
          }}
        />
      ))}
    </span>
  );
}

export function UsageDensityChrome({
  open,
  station,
  onOpenChange,
  onStationChange,
  intensity,
  onCycleIntensity,
  window: densityWindow,
  onWindowChange,
  compare,
  onCompareChange,
  animate,
  onAnimateChange,
  connectionsEnabled,
  onConnectionsToggle,
  botsVisible,
  onBotsVisibleChange,
  botsReduced,
  onBotsReducedChange,
  landmarkBeaconsVisible,
  onLandmarkBeaconsVisibleChange,
  attentionSignalsVisible,
  onAttentionSignalsVisibleChange,
  onOpenPalette,
  objects,
  attentionItems,
  selectedAttentionId,
  onSelectAttention,
  onReplyAttention,
  launchWorldCenter,
}: UsageDensityChromeProps) {
  const [objectQuery, setObjectQuery] = useState("");
  const [objectMenu, setObjectMenu] = useState<{
    x: number;
    y: number;
    item: StarboardObjectItem;
  } | null>(null);
  const [stationMenuOpen, setStationMenuOpen] = useState(false);
  const stationMenuRef = useRef<HTMLDivElement | null>(null);
  const objectClickTimerRef = useRef<number | null>(null);
  const activeStation = STATIONS.find((item) => item.id === station) ?? STATIONS[0];
  const selectStation = (nextStation: StarboardStation) => {
    onStationChange(nextStation);
    persistStarboardTab(nextStation);
    setStationMenuOpen(false);
  };
  const normalizedQuery = objectQuery.trim().toLowerCase();
  const visibleObjects = objects.filter((item) => {
    if (!normalizedQuery) return true;
    return `${item.label} ${item.subtitle ?? ""} ${KIND_LABEL[item.kind]}`.toLowerCase().includes(normalizedQuery);
  });

  useEffect(() => {
    if (!stationMenuOpen) return;
    function close(event: PointerEvent) {
      const menu = stationMenuRef.current;
      if (menu && menu.contains(event.target as Node)) return;
      setStationMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setStationMenuOpen(false);
    }
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [stationMenuOpen]);

  useEffect(() => {
    return () => {
      if (objectClickTimerRef.current !== null) {
        window.clearTimeout(objectClickTimerRef.current);
      }
    };
  }, []);

  const handleObjectClick = (item: StarboardObjectItem) => {
    if (!item.onDoubleClick) {
      item.onSelect();
      return;
    }
    if (objectClickTimerRef.current !== null) {
      window.clearTimeout(objectClickTimerRef.current);
    }
    objectClickTimerRef.current = window.setTimeout(() => {
      item.onSelect();
      objectClickTimerRef.current = null;
    }, 220);
  };

  const handleObjectDoubleClick = (item: StarboardObjectItem) => {
    if (!item.onDoubleClick) return;
    if (objectClickTimerRef.current !== null) {
      window.clearTimeout(objectClickTimerRef.current);
      objectClickTimerRef.current = null;
    }
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
          className="fixed bottom-0 right-0 top-0 z-[65] flex w-[560px] max-w-[calc(100vw-1rem)] flex-col border-l border-surface-border bg-surface-raised/95 text-sm text-text backdrop-blur"
          onPointerDown={(event) => event.stopPropagation()}
          onContextMenu={(event) => {
            event.preventDefault();
            event.stopPropagation();
          }}
          onWheelCapture={(event) => {
            event.stopPropagation();
          }}
        >
          <div className="flex items-center justify-between px-3 py-3">
            <div ref={stationMenuRef} className="relative min-w-0 flex-1">
              <button
                type="button"
                className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-surface-overlay/50"
                onClick={() => setStationMenuOpen((open) => !open)}
                aria-haspopup="menu"
                aria-expanded={stationMenuOpen}
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
                  {activeStation.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">Starboard</span>
                  <span className="block truncate text-base font-semibold text-text">{activeStation.label}</span>
                </span>
                <ChevronDown size={16} className="text-text-dim" />
              </button>
              {stationMenuOpen && (
                <div
                  role="menu"
                  className="absolute left-0 top-full z-[50003] mt-2 w-72 rounded-md border border-surface-border bg-surface-raised/95 p-1 backdrop-blur"
                  onPointerDown={(event) => event.stopPropagation()}
                  onContextMenu={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                >
                  {STATIONS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="menuitem"
                      className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left ${
                        station === item.id ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                      }`}
                      onClick={() => selectStation(item.id)}
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-surface-overlay/50">{item.icon}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium">{item.label}</span>
                        <span className="block truncate text-xs text-text-dim">{item.eyebrow}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
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

          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
              {station === "controls" ? (
                <>
                  <div className="mb-4">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">Controls</div>
                    <div className="mt-1 text-sm text-text-muted">Map view and canvas behavior.</div>
                  </div>

                  <PanelSection icon={<Command size={15} />} title="Commands">
                    <button
                      type="button"
                      onClick={onOpenPalette}
                      className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                    >
                      <span>Command palette</span>
                      <span className="font-mono text-[11px] text-text-dim">Ctrl K</span>
                    </button>
                  </PanelSection>

                  <PanelSection icon={<Eye size={15} />} title="View">
                    <SettingRow label="Attention signals">
                      <input
                        type="checkbox"
                        checked={attentionSignalsVisible}
                        onChange={(e) => onAttentionSignalsVisibleChange(e.target.checked)}
                        className="accent-accent"
                      />
                    </SettingRow>
                    <SettingRow label="Connection lines">
                      <input
                        type="checkbox"
                        checked={connectionsEnabled}
                        onChange={() => onConnectionsToggle()}
                        className="accent-accent"
                      />
                    </SettingRow>
                  </PanelSection>

                  <PanelSection icon={<Activity size={15} />} title="Activity">
                    <button
                      type="button"
                      onClick={onCycleIntensity}
                      title={INTENSITY_HINT[intensity]}
                      className="mb-2 inline-flex items-center rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                    >
                      <IntensityPips intensity={intensity} />
                      {INTENSITY_LABEL[intensity]}
                    </button>
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-text-muted">Window</span>
                      <div className="inline-flex overflow-hidden rounded-md bg-surface-overlay/60 p-0.5">
                        {WINDOWS.map((w) => (
                          <button
                            key={w}
                            type="button"
                            onClick={() => onWindowChange(w)}
                            className={`rounded px-2 py-1 text-xs ${
                              densityWindow === w
                                ? "bg-accent/[0.08] text-accent"
                                : "text-text-dim hover:bg-surface-overlay/80 hover:text-text"
                            }`}
                          >
                            {w}
                          </button>
                        ))}
                      </div>
                    </div>
                    <SettingRow label="Spike colors">
                      <input
                        type="checkbox"
                        checked={compare}
                        onChange={(e) => onCompareChange(e.target.checked)}
                        className="accent-accent"
                      />
                    </SettingRow>
                    <SettingRow label="Breathe">
                      <input
                        type="checkbox"
                        checked={animate}
                        onChange={(e) => onAnimateChange(e.target.checked)}
                        className="accent-accent"
                      />
                    </SettingRow>
                  </PanelSection>

                  <PanelSection icon={<Bot size={15} />} title="Bots">
                    <SettingRow label="Show bots">
                      <input
                        type="checkbox"
                        checked={botsVisible}
                        onChange={(e) => onBotsVisibleChange(e.target.checked)}
                        className="accent-accent"
                      />
                    </SettingRow>
                    <SettingRow label="Reduce bots">
                      <input
                        type="checkbox"
                        checked={botsReduced}
                        onChange={(e) => onBotsReducedChange(e.target.checked)}
                        disabled={!botsVisible}
                        className="accent-accent disabled:opacity-40"
                      />
                    </SettingRow>
                  </PanelSection>

                  <PanelSection icon={<MapPinned size={15} />} title="Wayfinding">
                    <SettingRow label="Edge beacons">
                      <input
                        type="checkbox"
                        checked={landmarkBeaconsVisible}
                        onChange={(e) => onLandmarkBeaconsVisibleChange(e.target.checked)}
                        className="accent-accent"
                      />
                    </SettingRow>
                  </PanelSection>
                </>
              ) : station === "objects" ? (
                <>
                  <div className="mb-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">Objects</div>
                      <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{visibleObjects.length}</span>
                    </div>
                    <div className="mt-1 text-sm text-text-muted">Nearest positioned items from the current view.</div>
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
                  <div className="space-y-1">
                    {visibleObjects.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => handleObjectClick(item)}
                        onDoubleClick={() => handleObjectDoubleClick(item)}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setObjectMenu({ x: event.clientX, y: event.clientY, item });
                        }}
                        className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-overlay/60"
                      >
                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${kindTone(item.kind)}`}>
                          {kindIcon(item.kind)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate text-sm font-medium text-text">{item.label}</span>
                            <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                              {KIND_LABEL[item.kind]}
                            </span>
                          </span>
                          <span className="block truncate text-xs text-text-dim">{item.subtitle ?? KIND_LABEL[item.kind]}</span>
                        </span>
                        <span className="shrink-0 text-xs text-text-dim">{formatDistance(item.distance)}</span>
                      </button>
                    ))}
                    {!visibleObjects.length && (
                      <div className="rounded-md bg-surface-overlay/30 px-3 py-6 text-center text-sm text-text-dim">
                        No positioned objects match.
                      </div>
                    )}
                  </div>
                </>
              ) : station === "attention" ? (
                <AttentionHubContent
                  items={attentionItems}
                  selectedId={selectedAttentionId}
                  onSelect={onSelectAttention}
                  onReply={onReplyAttention}
                />
              ) : station === "health" ? (
                <SummaryPanel embedded />
              ) : (
                <CanvasLibraryContent
                  embedded
                  worldCenter={launchWorldCenter}
                  onClose={() => onOpenChange(false)}
                />
              )}
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

function persistStarboardTab(tab: StarboardStation) {
  try {
    window.localStorage.setItem(STARBOARD_TAB_KEY, tab);
  } catch {
    /* storage disabled */
  }
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

function PanelSection({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">
        {icon}
        <span>{title}</span>
      </div>
      <div className="space-y-1 rounded-md bg-surface-overlay/30 p-2">
        {children}
      </div>
    </section>
  );
}

function SettingRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-h-9 cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay/60 hover:text-text">
      <span>{label}</span>
      {children}
    </label>
  );
}
