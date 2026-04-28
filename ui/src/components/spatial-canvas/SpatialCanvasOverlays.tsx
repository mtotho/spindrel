import type React from "react";
import { Move } from "lucide-react";
import { buildChannelSessionRoute, type ChannelSessionSurface } from "../../lib/channelSessionSurfaces";
import type { WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import { useUIStore } from "../../stores/ui";
import { ChatSession } from "../chat/ChatSession";
import { SessionPickerOverlay } from "../chat/SessionPickerOverlay";
import { AddWidgetButton, LensHint } from "./SpatialCanvasChrome";
import { DivePulseOverlay } from "./DivePulseOverlay";
import { MemoryObservationPanel } from "./MemoryObservatory";
import { Minimap } from "./Minimap";
import { SpatialContextMenu } from "./SpatialContextMenu";
import { SpatialEdgeBeacons } from "./SpatialEdgeBeacons";
import { SpatialSelectionRail } from "./SpatialSelectionRail";
import { UsageDensityChrome } from "./UsageDensityChrome";

type SpatialCanvasOverlaysProps = Record<string, any> & {
  navigate: (to: string, options?: any) => void;
  setPinPositionOverride: React.Dispatch<React.SetStateAction<any>>;
  setInteractionMode: React.Dispatch<React.SetStateAction<any>>;
  setDensityWindow: React.Dispatch<React.SetStateAction<any>>;
  setDensityCompare: React.Dispatch<React.SetStateAction<any>>;
  setDensityAnimate: React.Dispatch<React.SetStateAction<any>>;
  setConnectionsEnabled: React.Dispatch<React.SetStateAction<any>>;
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
    botsVisible,
    setBotsVisible,
    botsReduced,
    setBotsReduced,
    setLandmarkBeaconsVisible,
    attentionSignalsVisible,
    setAttentionSignalsVisible,
    starboardObjects,
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
    channelClusterMode,
  } = props;

  return (
    <>
      {!channelClusterMode && <LensHint />}
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
            openStarboardLaunch();
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
        <UsageDensityChrome
          intensity={densityIntensity}
          onCycleIntensity={cycleDensityIntensity}
          window={densityWindow}
          onWindowChange={setDensityWindow}
          compare={densityCompare}
          onCompareChange={setDensityCompare}
          animate={densityAnimate}
          onAnimateChange={setDensityAnimate}
          connectionsEnabled={connectionsEnabled}
          onConnectionsToggle={() => setConnectionsEnabled((v: any) => !v)}
          botsVisible={botsVisible}
          onBotsVisibleChange={setBotsVisible}
          botsReduced={botsReduced}
          onBotsReducedChange={setBotsReduced}
          landmarkBeaconsVisible={landmarkBeaconsVisible}
          onLandmarkBeaconsVisibleChange={setLandmarkBeaconsVisible}
          attentionSignalsVisible={attentionSignalsVisible}
          onAttentionSignalsVisibleChange={setAttentionSignalsVisible}
          onOpenPalette={() => useUIStore.getState().openPalette()}
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
          launchWorldCenter={
            pinPositionOverride
              ? { x: pinPositionOverride.x + 160, y: pinPositionOverride.y + 110 }
              : viewportSize.w && viewportSize.h
                ? {
                    x: (viewportSize.w / 2 - cameraRef.current.x) / cameraRef.current.scale,
                    y: (viewportSize.h / 2 - cameraRef.current.y) / cameraRef.current.scale,
                  }
                : null
          }
        />
      </div>
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
