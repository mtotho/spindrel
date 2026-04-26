import { useEffect, useRef } from "react";
import { dotColor } from "./ChannelTile";
import type { ChannelCluster } from "./spatialClustering";

interface ChannelClusterMarkerProps {
  cluster: ChannelCluster;
  zoom: number;
  showActivityGlow: boolean;
  maxClusterTokens: number;
  onFocus: () => void;
  onDiveWinner: () => void;
}

function channelName(cluster: ChannelCluster): string {
  return cluster.winner.channel.display_name || cluster.winner.channel.name;
}

export function ChannelClusterMarker({
  cluster,
  zoom,
  showActivityGlow,
  maxClusterTokens,
  onFocus,
  onDiveWinner,
}: ChannelClusterMarkerProps) {
  const clickTimerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (clickTimerRef.current !== null) window.clearTimeout(clickTimerRef.current);
    };
  }, []);

  const winner = cluster.winner;
  const hiddenCount = cluster.hiddenMembers.length;
  const effectiveScale = Math.max(0.05, zoom);
  const labelScale = Math.min(4.4, 1 / effectiveScale);
  const ratio = maxClusterTokens > 0 ? cluster.totalTokens / maxClusterTokens : 0;
  const glow = showActivityGlow && cluster.totalTokens > 0
    ? 0.22 + Math.sqrt(ratio) * 0.34
    : 0;

  return (
    <button
      type="button"
      data-tile-kind="channel-cluster"
      title={`${channelName(cluster)} and ${hiddenCount} nearby channel${hiddenCount === 1 ? "" : "s"}`}
      className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 cursor-zoom-in flex-col items-center justify-center gap-3 border-0 bg-transparent p-0 text-text"
      style={{ width: 270, minHeight: 170 }}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        if (clickTimerRef.current !== null) window.clearTimeout(clickTimerRef.current);
        clickTimerRef.current = window.setTimeout(() => {
          clickTimerRef.current = null;
          onFocus();
        }, 180);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        if (clickTimerRef.current !== null) {
          window.clearTimeout(clickTimerRef.current);
          clickTimerRef.current = null;
        }
        onDiveWinner();
      }}
    >
      <div className="relative flex h-[104px] w-[104px] items-center justify-center">
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
      </div>
      <div
        className="max-w-full truncate px-2 text-base font-semibold whitespace-nowrap"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
        {channelName(cluster)}
      </div>
    </button>
  );
}
