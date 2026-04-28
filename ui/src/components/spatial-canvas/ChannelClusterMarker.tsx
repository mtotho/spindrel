import { useRef } from "react";
import { dotColor } from "./spatialIdentity";
import type { ChannelCluster } from "./spatialClustering";

const OVERVIEW_MIN_SCALE = 0.03;

interface ChannelClusterMarkerProps {
  cluster: ChannelCluster;
  zoom: number;
  showActivityGlow: boolean;
  maxClusterTokens: number;
  widgetCount?: number;
  widgetOpacity?: number;
  onFocus: () => void;
}

function channelName(cluster: ChannelCluster): string {
  return cluster.winner.channel.display_name || cluster.winner.channel.name;
}

export function ChannelClusterMarker({
  cluster,
  zoom,
  showActivityGlow,
  maxClusterTokens,
  widgetCount = 0,
  widgetOpacity = 0,
  onFocus,
}: ChannelClusterMarkerProps) {
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const winner = cluster.winner;
  const hiddenCount = cluster.hiddenMembers.length;
  const effectiveScale = Math.max(OVERVIEW_MIN_SCALE, zoom);
  const markerScale = Math.max(1, 34 / (84 * effectiveScale));
  const labelScale = Math.max(1, 14 / (16 * effectiveScale));
  const ratio = maxClusterTokens > 0 ? cluster.totalTokens / maxClusterTokens : 0;
  const glow = showActivityGlow && cluster.totalTokens > 0
    ? 0.22 + Math.sqrt(ratio) * 0.34
    : 0;
  const widgetSatelliteCount = Math.min(widgetCount, 5);
  const focusCluster = () => onFocus();
  const focusPrimaryCluster = (e: { stopPropagation: () => void; button?: number }) => {
    e.stopPropagation();
    if (e.button === undefined || e.button === 0) focusCluster();
  };

  return (
    <button
      ref={buttonRef}
      type="button"
      data-tile-kind="channel-cluster"
      title={`Zoom to ${cluster.members.length} nearby channels`}
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center justify-center gap-3 border-0 bg-transparent p-0 text-text"
      style={{ width: 270, minHeight: 170 }}
      onPointerDownCapture={focusPrimaryCluster}
      onMouseDownCapture={focusPrimaryCluster}
      onPointerDown={focusPrimaryCluster}
      onMouseDown={focusPrimaryCluster}
      onPointerUp={focusPrimaryCluster}
      onClick={focusPrimaryCluster}
      onDoubleClick={focusPrimaryCluster}
    >
      <div
        className="relative flex h-[104px] w-[104px] items-center justify-center"
        style={{
          transform: `scale(${markerScale})`,
          transformOrigin: "center center",
        }}
      >
        {glow > 0 && (
          <div
            className="absolute inset-[-34px] rounded-full blur-xl"
            style={{
              background: dotColor(winner.channel.id),
              opacity: glow,
            }}
          />
        )}
        <div
          className="relative h-[84px] w-[84px] rounded-full shadow-md ring-2 ring-text/15"
          style={{ background: dotColor(winner.channel.id) }}
        />
        {cluster.hiddenMembers.slice(0, 4).map((member, index) => {
          const angle = -65 + index * 42;
          const r = 58;
          const x = Math.cos((angle * Math.PI) / 180) * r;
          const y = Math.sin((angle * Math.PI) / 180) * r;
          return (
            <span
              key={member.node.id}
              className="absolute h-5 w-5 rounded-full border-2 border-surface shadow-sm"
              style={{
                transform: `translate(${x}px, ${y}px)`,
                background: dotColor(member.channel.id),
              }}
            />
          );
        })}
        <span className="absolute -right-2 -top-1 rounded-full border border-surface-border bg-surface-raised px-2 py-0.5 text-xs font-semibold text-text shadow-sm">
          +{hiddenCount}
        </span>
        {Array.from({ length: widgetSatelliteCount }).map((_, index) => {
          const angle = 100 + index * (widgetSatelliteCount > 1 ? 28 : 0);
          const r = 72;
          const x = Math.cos((angle * Math.PI) / 180) * r;
          const y = Math.sin((angle * Math.PI) / 180) * r;
          return (
            <span
              key={`widget-${index}`}
              className="absolute h-4 w-4 rotate-45 rounded-[4px] border border-accent/70 bg-accent/15 shadow-sm"
              style={{
                transform: `translate(${x}px, ${y}px) rotate(45deg)`,
                opacity: widgetOpacity,
              }}
            />
          );
        })}
        {widgetCount > 5 && (
          <span
            className="absolute -bottom-7 left-1/2 -translate-x-1/2 rounded-full border border-surface-border bg-surface-raised px-2 py-0.5 text-[10px] font-semibold text-text shadow-sm"
            style={{ opacity: widgetOpacity }}
          >
            +{widgetCount - 5} widgets
          </span>
        )}
      </div>
      <div
        className="flex max-w-full flex-col items-center gap-0.5 px-2 text-center"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
        <span className="text-base font-semibold whitespace-nowrap">
          {cluster.members.length} channels
        </span>
        <span className="max-w-full truncate text-xs font-medium text-text-muted whitespace-nowrap">
          near {channelName(cluster)}
        </span>
      </div>
    </button>
  );
}
