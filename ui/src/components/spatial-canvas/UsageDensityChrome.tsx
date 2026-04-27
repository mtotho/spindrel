import { useState } from "react";
import type { ReactNode } from "react";
import { Activity, Bot, Box, Command, Eye, Hash, LayoutList, MapPin, MapPinned, PanelRightOpen, Radar, Search, Settings2, X } from "lucide-react";
import type { DensityWindow } from "./UsageDensityLayer";
import type { DensityIntensity } from "./spatialGeometry";

export interface StarboardObjectItem {
  id: string;
  label: string;
  kind: "channel" | "widget" | "bot" | "landmark";
  subtitle?: string;
  worldX: number;
  worldY: number;
  distance: number;
  onSelect: () => void;
}

interface UsageDensityChromeProps {
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

type StarboardTab = "controls" | "objects";

const KIND_LABEL: Record<StarboardObjectItem["kind"], string> = {
  channel: "Channel",
  widget: "Widget",
  bot: "Bot",
  landmark: "Landmark",
};

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
}: UsageDensityChromeProps) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<StarboardTab>("controls");
  const [objectQuery, setObjectQuery] = useState("");
  const normalizedQuery = objectQuery.trim().toLowerCase();
  const visibleObjects = objects.filter((item) => {
    if (!normalizedQuery) return true;
    return `${item.label} ${item.subtitle ?? ""} ${KIND_LABEL[item.kind]}`.toLowerCase().includes(normalizedQuery);
  });

  return (
    <div
      className="flex flex-row items-stretch gap-2"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={() => setPanelOpen(true)}
        aria-expanded={panelOpen}
        aria-label="Open Starboard"
        title="Open Starboard"
        className={`inline-flex h-10 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors ${
          panelOpen
            ? "bg-accent/[0.08] text-accent"
            : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
        }`}
      >
        <PanelRightOpen size={16} />
        <span className="hidden sm:inline">Starboard</span>
      </button>
      {panelOpen && (
        <aside
          className="fixed bottom-0 right-0 top-0 z-[65] flex w-[520px] max-w-[calc(100vw-1rem)] flex-col border-l border-surface-border bg-surface-raised/95 text-sm text-text backdrop-blur"
          onPointerDown={(event) => event.stopPropagation()}
          onWheel={(event) => event.stopPropagation()}
        >
          <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-dim">Canvas</div>
              <div className="mt-0.5 text-base font-semibold">Starboard</div>
            </div>
            <button
              type="button"
              className="rounded-md p-2 text-text-muted hover:bg-surface-overlay/60 hover:text-text"
              onClick={() => setPanelOpen(false)}
              aria-label="Close Starboard"
              title="Close"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex min-h-0 flex-1">
            <nav className="w-28 border-r border-surface-border/70 p-2">
              <button
                type="button"
                onClick={() => setActiveTab("controls")}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium ${
                  activeTab === "controls"
                    ? "sidebar-item-active text-accent"
                    : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                }`}
              >
                <Settings2 size={15} />
                Controls
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("objects")}
                className={`mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium ${
                  activeTab === "objects"
                    ? "sidebar-item-active text-accent"
                    : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                }`}
              >
                <LayoutList size={15} />
                Objects
              </button>
            </nav>

            <div className="min-w-0 flex-1 overflow-y-auto p-4">
              {activeTab === "controls" ? (
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
              ) : (
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
                        onClick={item.onSelect}
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
              )}
            </div>
          </div>
        </aside>
      )}
    </div>
  );
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
