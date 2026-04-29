import type React from "react";
import { Activity, Bot, Command, Eye, MapPinned, Move, Navigation, PanelRightOpen, Route, Settings2 } from "lucide-react";
import { buildChannelSessionRoute, type ChannelSessionSurface } from "../../lib/channelSessionSurfaces";
import type { WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import { useUIStore } from "../../stores/ui";
import { ChatSession } from "../chat/ChatSession";
import { SessionPickerOverlay } from "../chat/SessionPickerOverlay";
import { AddWidgetButton } from "./SpatialCanvasChrome";
import { CanvasLibrarySheet } from "./CanvasLibrarySheet";
import { DivePulseOverlay } from "./DivePulseOverlay";
import { MemoryObservationPanel } from "./MemoryObservatory";
import { Minimap } from "./Minimap";
import { SpatialContextMenu } from "./SpatialContextMenu";
import { SpatialEdgeBeacons } from "./SpatialEdgeBeacons";
import { SpatialSelectionRail } from "./SpatialSelectionRail";
import { ActionCompass } from "./SpatialActionCues";
import { UsageDensityChrome } from "./UsageDensityChrome";

type SpatialCanvasOverlaysProps = Record<string, any> & {
  navigate: (to: string, options?: any) => void;
  setPinPositionOverride: React.Dispatch<React.SetStateAction<any>>;
  setInteractionMode: React.Dispatch<React.SetStateAction<any>>;
  setDensityWindow: React.Dispatch<React.SetStateAction<any>>;
  setDensityCompare: React.Dispatch<React.SetStateAction<any>>;
  setDensityAnimate: React.Dispatch<React.SetStateAction<any>>;
  setConnectionsEnabled: React.Dispatch<React.SetStateAction<any>>;
  setCanvasLibraryOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setBotsVisible: React.Dispatch<React.SetStateAction<any>>;
  setBotsReduced: React.Dispatch<React.SetStateAction<any>>;
  setLandmarkBeaconsVisible: React.Dispatch<React.SetStateAction<any>>;
  setAttentionSignalsVisible: React.Dispatch<React.SetStateAction<any>>;
  setStarboardOpen: React.Dispatch<React.SetStateAction<any>>;
  setStarboardStation: React.Dispatch<React.SetStateAction<any>>;
  setSelectedAttentionId: React.Dispatch<React.SetStateAction<any>>;
  setMemorySelection: React.Dispatch<React.SetStateAction<any>>;
  setMinimapVisible: React.Dispatch<React.SetStateAction<any>>;
  setContextMenu: React.Dispatch<React.SetStateAction<any>>;
  setOpenBotChat: React.Dispatch<React.SetStateAction<any>>;
  setSessionPickerOpen: React.Dispatch<React.SetStateAction<any>>;
};

const ACTIVITY_LABEL: Record<string, string> = {
  off: "Off",
  subtle: "Subtle",
  bold: "Bright",
};

const TRAIL_LABEL: Record<string, string> = {
  off: "Off",
  hover: "Hover",
  all: "All",
};

export function SpatialCanvasOverlays(props: SpatialCanvasOverlaysProps) {
  const {
    selectionRail,
    diveCandidate,
    memorySelection,
    setMemorySelection,
    landmarkBeaconsVisible,
    camera,
    viewportSize,
    edgeBeacons,
    setPinPositionOverride,
    canvasLibraryOpen,
    setCanvasLibraryOpen,
    openStarboardLaunch,
    interactionMode,
    setInteractionMode,
    densityIntensity,
    cycleDensityIntensity,
    densityWindow,
    setDensityWindow,
    densityCompare,
    setDensityCompare,
    densityAnimate,
    setDensityAnimate,
    connectionsEnabled,
    setConnectionsEnabled,
    trailsMode,
    cycleTrailsMode,
    botsVisible,
    setBotsVisible,
    botsReduced,
    setBotsReduced,
    setLandmarkBeaconsVisible,
    attentionSignalsVisible,
    setAttentionSignalsVisible,
    starboardObjects,
    viewportBbox,
    highlightedActionCueId,
    setHighlightedActionCueId,
    starboardOpen,
    starboardStation,
    setStarboardOpen,
    setStarboardStation,
    attentionItems,
    selectedAttentionId,
    setSelectedAttentionId,
    handleAttentionReply,
    selectedStarboardObject,
    pinPositionOverride,
    cameraRef,
    minimapVisible,
    nodes,
    flyToWorldPoint,
    setMinimapVisible,
    contextMenu,
    setContextMenu,
    openBotChat,
    setOpenBotChat,
    sessionPickerOpen,
    setSessionPickerOpen,
    navigate,
  } = props;
  const launchWorldCenter = pinPositionOverride
    ? { x: pinPositionOverride.x + 160, y: pinPositionOverride.y + 110 }
    : viewportSize.w && viewportSize.h
      ? {
          x: (viewportSize.w / 2 - cameraRef.current.x) / cameraRef.current.scale,
          y: (viewportSize.h / 2 - cameraRef.current.y) / cameraRef.current.scale,
        }
      : null;

  return (
    <>
      {selectionRail && (
        <SpatialSelectionRail
          x={selectionRail.x}
          y={selectionRail.y}
          label={selectionRail.label}
          meta={selectionRail.meta}
          leading={selectionRail.leading}
          actions={selectionRail.actions}
        />
      )}
      {diveCandidate && (
        <DivePulseOverlay channelLabel={diveCandidate.label} />
      )}
      <MemoryObservationPanel
        selection={memorySelection}
        onClose={() => setMemorySelection(null)}
      />
      <ActionCompass
        objects={starboardObjects ?? []}
        viewport={viewportBbox}
        selectedObjectId={selectedStarboardObject?.id ?? null}
        highlightedObjectId={highlightedActionCueId ?? null}
        onHighlight={setHighlightedActionCueId}
        collapsed={Boolean(starboardOpen && selectedStarboardObject)}
      />
      {landmarkBeaconsVisible && (
        <SpatialEdgeBeacons
          camera={camera}
          viewport={viewportSize}
          beacons={edgeBeacons}
          maxVisible={9}
        />
      )}
      <div
        className="absolute top-4 right-4 z-[2] flex flex-row items-stretch gap-2"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <AddWidgetButton
          onClick={() => {
            setPinPositionOverride(null);
            setCanvasLibraryOpen(true);
          }}
        />
        <button
          type="button"
          title={interactionMode === "arrange" ? "Arrange mode on. Click to return to Browse." : "Arrange items"}
          aria-pressed={interactionMode === "arrange"}
          onClick={() => setInteractionMode((mode: any) => (mode === "arrange" ? "browse" : "arrange"))}
          className={`inline-flex h-10 items-center gap-1.5 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors ${
            interactionMode === "arrange"
              ? "border-accent/50 bg-accent/10 text-accent"
              : "border-surface-border/70 bg-surface-raised/80 text-text-muted hover:bg-surface-overlay hover:text-text"
          }`}
        >
          <Move size={16} />
          {interactionMode === "arrange" && <span className="hidden sm:inline">Arrange</span>}
        </button>
        <CanvasViewControls
          densityIntensity={densityIntensity}
          onCycleDensityIntensity={cycleDensityIntensity}
          densityWindow={densityWindow}
          onDensityWindowChange={setDensityWindow}
          densityCompare={densityCompare}
          onDensityCompareChange={setDensityCompare}
          densityAnimate={densityAnimate}
          onDensityAnimateChange={setDensityAnimate}
          connectionsEnabled={connectionsEnabled}
          onConnectionsEnabledChange={setConnectionsEnabled}
          trailsMode={trailsMode}
          onCycleTrailsMode={cycleTrailsMode}
          botsVisible={botsVisible}
          onBotsVisibleChange={setBotsVisible}
          botsReduced={botsReduced}
          onBotsReducedChange={setBotsReduced}
          landmarkBeaconsVisible={landmarkBeaconsVisible}
          onLandmarkBeaconsVisibleChange={setLandmarkBeaconsVisible}
          attentionSignalsVisible={attentionSignalsVisible}
          onAttentionSignalsVisibleChange={setAttentionSignalsVisible}
          minimapVisible={minimapVisible}
          onMinimapVisibleChange={setMinimapVisible}
          onOpenPalette={() => useUIStore.getState().openPalette()}
        />
        <UsageDensityChrome
          objects={starboardObjects}
          open={starboardOpen}
          station={starboardStation}
          onOpenChange={setStarboardOpen}
          onStationChange={setStarboardStation}
          attentionItems={attentionItems ?? []}
          selectedAttentionId={selectedAttentionId}
          onSelectAttention={(item: WorkspaceAttentionItem | null) => setSelectedAttentionId(item?.id ?? null)}
          onReplyAttention={handleAttentionReply}
          selectedObject={selectedStarboardObject}
          navigate={navigate}
        />
      </div>
      <CanvasLibrarySheet
        open={canvasLibraryOpen}
        onClose={() => setCanvasLibraryOpen(false)}
        worldCenter={launchWorldCenter}
      />
      {minimapVisible && (
        <Minimap
          camera={camera}
          viewport={viewportSize}
          nodes={nodes ?? []}
          onJumpTo={flyToWorldPoint}
          onClose={() => setMinimapVisible(false)}
        />
      )}
      {contextMenu && (
        <SpatialContextMenu
          screenX={contextMenu.screenX}
          screenY={contextMenu.screenY}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}
      {openBotChat && (
        <ChatSession
          source={{ kind: "channel", channelId: openBotChat.channelId }}
          shape="dock"
          open={true}
          onClose={() => {
            setOpenBotChat(null);
            setSessionPickerOpen(false);
          }}
          title={`${openBotChat.botName} in #${openBotChat.channelName}`}
          initiallyExpanded
          dockCollapsedTitle={openBotChat.botName}
          dockCollapsedSubtitle={`#${openBotChat.channelName}`}
          dismissMode="close"
          onOpenSessions={() => setSessionPickerOpen(true)}
        />
      )}
      {openBotChat && (
        <SessionPickerOverlay
          open={sessionPickerOpen}
          onClose={() => setSessionPickerOpen(false)}
          channelId={openBotChat.channelId}
          botId={openBotChat.botId}
          channelLabel={openBotChat.channelName}
          onActivateSurface={(surface: ChannelSessionSurface) => {
            setSessionPickerOpen(false);
            setOpenBotChat(null);
            navigate(buildChannelSessionRoute(openBotChat.channelId, surface));
          }}
        />
      )}
    </>
  );
}

function CanvasViewControls({
  densityIntensity,
  onCycleDensityIntensity,
  densityWindow,
  onDensityWindowChange,
  densityCompare,
  onDensityCompareChange,
  densityAnimate,
  onDensityAnimateChange,
  connectionsEnabled,
  onConnectionsEnabledChange,
  trailsMode,
  onCycleTrailsMode,
  botsVisible,
  onBotsVisibleChange,
  botsReduced,
  onBotsReducedChange,
  landmarkBeaconsVisible,
  onLandmarkBeaconsVisibleChange,
  attentionSignalsVisible,
  onAttentionSignalsVisibleChange,
  minimapVisible,
  onMinimapVisibleChange,
  onOpenPalette,
}: {
  densityIntensity: string;
  onCycleDensityIntensity: () => void;
  densityWindow: string;
  onDensityWindowChange: (value: any) => void;
  densityCompare: boolean;
  onDensityCompareChange: (value: boolean) => void;
  densityAnimate: boolean;
  onDensityAnimateChange: (value: boolean) => void;
  connectionsEnabled: boolean;
  onConnectionsEnabledChange: React.Dispatch<React.SetStateAction<any>>;
  trailsMode: string;
  onCycleTrailsMode: () => void;
  botsVisible: boolean;
  onBotsVisibleChange: (value: boolean) => void;
  botsReduced: boolean;
  onBotsReducedChange: (value: boolean) => void;
  landmarkBeaconsVisible: boolean;
  onLandmarkBeaconsVisibleChange: (value: boolean) => void;
  attentionSignalsVisible: boolean;
  onAttentionSignalsVisibleChange: (value: boolean) => void;
  minimapVisible: boolean;
  onMinimapVisibleChange: (value: boolean) => void;
  onOpenPalette: () => void;
}) {
  return (
    <details className="relative">
      <summary
        aria-label="Canvas view controls"
        className="inline-flex h-10 cursor-pointer list-none items-center gap-1.5 rounded-md border border-surface-border/70 bg-surface-raised/80 px-3 text-sm font-medium text-text-muted shadow-sm transition-colors hover:bg-surface-overlay hover:text-text [&::-webkit-details-marker]:hidden"
      >
        <Settings2 size={16} />
        <span className="hidden sm:inline">View</span>
      </summary>
      <div
        data-testid="canvas-view-controls"
        className="absolute right-0 top-full mt-2 w-72 rounded-md border border-surface-border bg-surface-raised/95 p-2 text-sm text-text shadow-2xl backdrop-blur"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          onClick={onOpenPalette}
          className="mb-2 flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-text-muted hover:bg-surface-overlay/60 hover:text-text"
        >
          <span className="inline-flex items-center gap-2"><Command size={15} /> Command palette</span>
          <span className="font-mono text-[11px] text-text-dim">Ctrl K</span>
        </button>
        <ViewControlSection icon={<Eye size={15} />} title="Signals">
          <ToggleRow label="Attention markers" checked={attentionSignalsVisible} onChange={onAttentionSignalsVisibleChange} />
          <ToggleRow label="Connection lines" checked={connectionsEnabled} onChange={() => onConnectionsEnabledChange((value: boolean) => !value)} />
          <ToggleRow label="Edge beacons" checked={landmarkBeaconsVisible} onChange={onLandmarkBeaconsVisibleChange} />
          <ToggleRow label="Minimap" checked={minimapVisible} onChange={onMinimapVisibleChange} />
        </ViewControlSection>
        <ViewControlSection icon={<Activity size={15} />} title="Activity">
          <button
            type="button"
            onClick={onCycleDensityIntensity}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-text-muted hover:bg-surface-overlay/60 hover:text-text"
          >
            <span>Activity halos</span>
            <span className="text-xs text-text-dim">{ACTIVITY_LABEL[densityIntensity] ?? densityIntensity}</span>
          </button>
          <div className="flex items-center justify-between gap-2 px-2 py-1.5">
            <span className="text-text-muted">Window</span>
            <span className="inline-flex rounded-md bg-surface-overlay/50 p-0.5">
              {["24h", "7d", "30d"].map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onDensityWindowChange(value)}
                  className={`rounded px-2 py-1 text-xs ${densityWindow === value ? "bg-accent/[0.08] text-accent" : "text-text-dim hover:text-text"}`}
                >
                  {value}
                </button>
              ))}
            </span>
          </div>
          <ToggleRow label="Spike colors" checked={densityCompare} onChange={onDensityCompareChange} />
          <ToggleRow label="Breathe" checked={densityAnimate} onChange={onDensityAnimateChange} />
        </ViewControlSection>
        <ViewControlSection icon={<Bot size={15} />} title="Objects">
          <ToggleRow label="Show bots" checked={botsVisible} onChange={onBotsVisibleChange} />
          <ToggleRow label="Reduce bots" checked={botsReduced} onChange={onBotsReducedChange} disabled={!botsVisible} />
          <button
            type="button"
            onClick={onCycleTrailsMode}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-text-muted hover:bg-surface-overlay/60 hover:text-text"
          >
            <span className="inline-flex items-center gap-2"><Route size={14} /> Trails</span>
            <span className="text-xs text-text-dim">{TRAIL_LABEL[trailsMode] ?? trailsMode}</span>
          </button>
        </ViewControlSection>
        <div className="mt-2 flex items-center gap-2 px-2 py-1 text-[11px] text-text-dim">
          <MapPinned size={13} />
          View settings stay on the canvas.
        </div>
      </div>
    </details>
  );
}

function ViewControlSection({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-surface-border/60 py-2 first:border-t-0">
      <div className="mb-1 flex items-center gap-2 px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
        {icon}
        {title}
      </div>
      <div className="space-y-0.5">{children}</div>
    </section>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-center justify-between rounded-md px-2 py-1.5 text-text-muted ${disabled ? "opacity-45" : "hover:bg-surface-overlay/60 hover:text-text"}`}>
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="accent-accent"
      />
    </label>
  );
}
