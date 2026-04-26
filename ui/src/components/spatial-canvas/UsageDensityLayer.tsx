import { useMemo } from "react";
import { useUsageBreakdown, type BreakdownGroup } from "../../api/hooks/useUsage";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { UsageHalo } from "./UsageHalo";
import { channelHue } from "./ChannelTile";
import type { DensityIntensity, DensityWindow } from "./spatialGeometry";

export type { DensityWindow };

/**
 * Per-channel token-usage density layer. Renders a glow halo behind each
 * channel tile, sized + alpha-scaled by token volume. Hue defaults to the
 * channel's stable hue (`channelHue(id)`) so the halo amplifies the dot's
 * existing identity rather than introducing a parallel color system.
 *
 * Two intensity tiers in the standard control surface:
 *   - subtle: small radius, low opacity, ambient signal you don't need to
 *     opt into. The default state.
 *   - bold: ~1.7x radius and opacity, easier to compare across the canvas
 *     at a glance.
 *
 * Compare mode (formerly "Deviation only") tints by `current/baseline`
 * ratio instead of channel hue: cool below baseline, warm above. Useful
 * for spotting spikes; off by default.
 *
 * Volume → radius uses a sqrt-of-ratio curve normalized against the
 * heaviest spender visible. Sqrt is the right shape to avoid the log
 * compression that made 200k vs 1.5m look identical (log(2e5+1)/log(1.5e6+1)
 * ≈ 0.86 — barely distinguishable). With sqrt, 200k vs 1.5m of the same
 * max reads as ~36% vs 100% radius, so the difference is unmistakable.
 *
 * NOT projected through the P16 lens — fisheye-warped halos misread volume.
 * Halos stay round in world space. Slight desync at the lens edge accepted
 * (halos are ambient signal, not foreground content).
 */

interface UsageDensityLayerProps {
  nodes: SpatialNode[];
  intensity: Exclude<DensityIntensity, "off">;
  window: DensityWindow;
  compare: boolean;
  animate: boolean;
}

const WINDOW_HOURS: Record<DensityWindow, number> = {
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
};

interface IntensityRamp {
  /** World-px halo radius range. */
  radiusMin: number;
  radiusMax: number;
  /** Opacity range applied on top of the t-curve. Bold rides higher. */
  opacityMin: number;
  opacityMax: number;
  /** HSL saturation/lightness for channel-hued halos. */
  saturation: number;
  lightness: number;
}

const RAMPS: Record<Exclude<DensityIntensity, "off">, IntensityRamp> = {
  subtle: {
    radiusMin: 60,
    radiusMax: 220,
    opacityMin: 0.15,
    opacityMax: 0.42,
    saturation: 60,
    lightness: 65,
  },
  bold: {
    radiusMin: 100,
    radiusMax: 360,
    opacityMin: 0.30,
    opacityMax: 0.78,
    saturation: 75,
    lightness: 55,
  },
};

function isoHoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

function nowIso(): string {
  return new Date().toISOString();
}

/** Map deviation ratio (current/baseline) to a hue: <1 cool, >1 warm. */
function hueForDeviation(ratio: number): number {
  // log around 1.0 so 2x and 0.5x are equidistant from neutral.
  const lr = Math.log2(Math.max(0.05, ratio));
  // Clamp to [-2, +2] (4x in either direction) for stable color range.
  const t = Math.min(1, Math.max(-1, lr / 2));
  // -1 → blue (220), 0 → green-ish (140), +1 → red (0)
  if (t >= 0) return 140 - t * 140;
  return 140 + (-t) * 80; // 140 → 220
}

export function UsageDensityLayer({
  nodes,
  intensity,
  window: densityWindow,
  compare,
  animate,
}: UsageDensityLayerProps) {
  const after = useMemo(() => isoHoursAgo(WINDOW_HOURS[densityWindow]), [densityWindow]);
  const before = useMemo(() => nowIso(), [densityWindow]);
  const baselineAfter = useMemo(
    () => isoHoursAgo(WINDOW_HOURS[densityWindow] * 2),
    [densityWindow],
  );
  const baselineBefore = useMemo(
    () => isoHoursAgo(WINDOW_HOURS[densityWindow]),
    [densityWindow],
  );

  const current = useUsageBreakdown({ group_by: "channel", after, before });
  const baseline = useUsageBreakdown({
    group_by: "channel",
    after: baselineAfter,
    before: baselineBefore,
  }, { enabled: compare });

  const groupsByChannel = useMemo(() => {
    const m = new Map<string, BreakdownGroup>();
    for (const g of current.data?.groups ?? []) {
      if (g.key) m.set(g.key, g);
    }
    return m;
  }, [current.data]);

  const baselineByChannel = useMemo(() => {
    if (!compare) return new Map<string, BreakdownGroup>();
    const m = new Map<string, BreakdownGroup>();
    for (const g of baseline.data?.groups ?? []) {
      if (g.key) m.set(g.key, g);
    }
    return m;
  }, [baseline.data, compare]);

  const maxTokens = useMemo(() => {
    let m = 0;
    for (const g of groupsByChannel.values()) {
      if (g.tokens > m) m = g.tokens;
    }
    return m;
  }, [groupsByChannel]);

  if (!current.data) return null;

  const ramp = RAMPS[intensity];

  return (
    <>
      {nodes.map((node) => {
        if (!node.channel_id) return null;
        const g = groupsByChannel.get(node.channel_id);
        if (!g || g.tokens === 0) return null;

        // Sqrt-of-ratio against the heaviest spender. Linear felt right
        // initially, but a workspace where one channel does 90% of traffic
        // would render every other channel as a tiny dot; sqrt gives small
        // channels a visible-but-clearly-smaller halo while still letting
        // the heavy channel dominate. Crucially, 200k vs 1.5m at the same
        // max reads as t=0.365 vs t=1.0 — clearly distinct.
        const ratio = maxTokens > 0 ? g.tokens / maxTokens : 0;
        const t = Math.sqrt(ratio);
        const radius = ramp.radiusMin + (ramp.radiusMax - ramp.radiusMin) * t;
        // Opacity: also sqrt-curved so big halos read brighter, not just
        // bigger. Together with radius this creates a strong gradient
        // between volumes.
        const opacity = ramp.opacityMin + (ramp.opacityMax - ramp.opacityMin) * t;

        let hue: number;
        let saturation = ramp.saturation;
        let lightness = ramp.lightness;
        let title: string;

        if (compare) {
          const baseG = baselineByChannel.get(node.channel_id);
          const baseTokens = baseG?.tokens ?? 0;
          // No baseline (or microscopic) = neutral. Treat <1k as noise floor.
          const r = baseTokens > 1000 ? g.tokens / baseTokens : 1.0;
          hue = hueForDeviation(r);
          // Spike colors should pop — override the per-tier saturation.
          saturation = 78;
          lightness = 55;
          const ratioStr = baseTokens > 1000 ? `${r.toFixed(2)}× prior period` : "no baseline";
          title = `${g.label} · ${g.tokens.toLocaleString()} tokens · ${ratioStr} · ${g.calls} calls`;
        } else {
          // Channel hue keeps the halo coupled to the dot's identity.
          hue = channelHue(node.channel_id);
          const cost = g.cost ?? 0;
          const costStr = cost > 0 ? ` · $${cost.toFixed(2)}` : "";
          title = `${g.label} · ${g.tokens.toLocaleString()} tokens${costStr} · ${g.calls} calls`;
        }

        // Larger halos breathe slower (perceived weight). 4s → 8s range.
        const breathSeconds = 4 + t * 4;

        const cx = node.world_x + node.world_w / 2;
        const cy = node.world_y + node.world_h / 2;

        return (
          <UsageHalo
            key={node.id}
            centerX={cx}
            centerY={cy}
            radius={radius}
            hue={hue}
            saturation={saturation}
            lightness={lightness}
            opacity={opacity}
            animate={animate}
            breathSeconds={breathSeconds}
            title={title}
          />
        );
      })}
    </>
  );
}
