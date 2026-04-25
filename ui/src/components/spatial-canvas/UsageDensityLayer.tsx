import { useMemo } from "react";
import { useUsageBreakdown, type BreakdownGroup } from "../../api/hooks/useUsage";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { UsageHalo } from "./UsageHalo";

/**
 * Per-channel token-usage density layer. Renders a glow halo behind each
 * channel tile, sized by token volume (log-scaled across the visible set)
 * and tinted by either cost intensity (cost-per-token) or deviation ratio
 * (current / baseline). Toggleable via `UsageDensityChrome`.
 *
 * Rendered inside the canvas's world-transformed div so pan/zoom apply for
 * free. NOT projected through the P16 lens — fisheye-warped halos misread
 * volume; halos stay round in world space.
 */

export type DensityWindow = "24h" | "7d" | "30d";
export type DensityMode = "absolute" | "deviation";

interface UsageDensityLayerProps {
  nodes: SpatialNode[];
  window: DensityWindow;
  mode: DensityMode;
  animate: boolean;
}

const WINDOW_HOURS: Record<DensityWindow, number> = {
  "24h": 24,
  "7d": 24 * 7,
  "30d": 24 * 30,
};

// Halo radius range in world px. Scales with the heaviest spender in the set
// — small workspaces don't get tiny halos and busy workspaces don't blow out.
const RADIUS_MIN = 110;
const RADIUS_MAX = 320;

function isoHoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

function nowIso(): string {
  return new Date().toISOString();
}

/** Map cost-per-token (USD/1M) to a hue: cool blue → warm red. */
function hueForCostIntensity(usdPerMillion: number): number {
  // Calibrated for current pricing: Haiku ≈ $1, Sonnet ≈ $5, Opus ≈ $20+/1M.
  // log-scale so the cool-warm ramp spans the price range smoothly.
  const t = Math.min(1, Math.max(0, Math.log10(Math.max(0.1, usdPerMillion) / 1) / 2));
  // 220° (blue) → 0° (red) via 180° (cyan), 120° (green), 60° (yellow), 30° (orange)
  return 220 - t * 220;
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
  window,
  mode,
  animate,
}: UsageDensityLayerProps) {
  const after = useMemo(() => isoHoursAgo(WINDOW_HOURS[window]), [window]);
  const before = useMemo(() => nowIso(), [window]); // recomputed when window changes
  const baselineAfter = useMemo(
    () => isoHoursAgo(WINDOW_HOURS[window] * 2),
    [window],
  );
  const baselineBefore = useMemo(
    () => isoHoursAgo(WINDOW_HOURS[window]),
    [window],
  );

  const current = useUsageBreakdown({ group_by: "channel", after, before });
  const baseline = useUsageBreakdown({
    group_by: "channel",
    after: baselineAfter,
    before: baselineBefore,
    // Don't refetch baseline when not in deviation mode — but querykey
    // already keys on params so flipping mode is cheap.
  });

  const groupsByChannel = useMemo(() => {
    const m = new Map<string, BreakdownGroup>();
    for (const g of current.data?.groups ?? []) {
      if (g.key) m.set(g.key, g);
    }
    return m;
  }, [current.data]);

  const baselineByChannel = useMemo(() => {
    const m = new Map<string, BreakdownGroup>();
    for (const g of baseline.data?.groups ?? []) {
      if (g.key) m.set(g.key, g);
    }
    return m;
  }, [baseline.data]);

  const maxTokens = useMemo(() => {
    let m = 0;
    for (const g of groupsByChannel.values()) {
      if (g.tokens > m) m = g.tokens;
    }
    return m;
  }, [groupsByChannel]);

  if (!current.data) return null;

  return (
    <>
      {nodes.map((node) => {
        if (!node.channel_id) return null;
        const g = groupsByChannel.get(node.channel_id);
        if (!g || g.tokens === 0) return null;

        // Log-scaled radius, normalized against the workspace's heaviest
        // spender — readable both in small and busy workspaces.
        const t = maxTokens > 0
          ? Math.log(g.tokens + 1) / Math.log(maxTokens + 1)
          : 0;
        const radius = RADIUS_MIN + (RADIUS_MAX - RADIUS_MIN) * t;

        let hue: number;
        let title: string;
        if (mode === "deviation") {
          const baseG = baselineByChannel.get(node.channel_id);
          const baseTokens = baseG?.tokens ?? 0;
          // No baseline = neutral. Tiny baselines (< 1k tokens) are noisy —
          // also treat as neutral so a sneeze doesn't read as a 50x spike.
          const ratio = baseTokens > 1000 ? g.tokens / baseTokens : 1.0;
          hue = hueForDeviation(ratio);
          const ratioStr = baseTokens > 1000 ? `${ratio.toFixed(2)}× baseline` : "no baseline";
          title = `${g.label} · ${g.tokens.toLocaleString()} tokens · ${ratioStr} · ${g.calls} calls`;
        } else {
          const cost = g.cost ?? 0;
          // Avoid div-by-zero; very low-volume channels read cool by default.
          const usdPerMillion = g.tokens > 0 ? (cost / g.tokens) * 1_000_000 : 0;
          hue = hueForCostIntensity(usdPerMillion);
          const costStr = cost > 0 ? `$${cost.toFixed(2)}` : "—";
          title = `${g.label} · ${g.tokens.toLocaleString()} tokens · ${costStr} · ${g.calls} calls`;
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
            saturation={70}
            lightness={55}
            opacity={0.35 + t * 0.35}
            animate={animate}
            breathSeconds={breathSeconds}
            title={title}
          />
        );
      })}
    </>
  );
}
