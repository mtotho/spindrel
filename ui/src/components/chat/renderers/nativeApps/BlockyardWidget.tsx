import { useMemo, useState } from "react";
import { Plus, Settings, ChevronRight } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import {
  PreviewCard,
  type NativeAppRendererProps,
  useNativeEnvelopeState,
} from "./shared";
import { WidgetSettingsDrawer, WidgetSettingsSection } from "./WidgetSettingsDrawer";
import {
  GameParticipantsSection,
  GamePhaseSection,
  GameTurnLogSection,
  type GamePhase,
} from "./games/GameSettingsSections";

// ── Types ────────────────────────────────────────────────────────────────

type BlockType =
  | "stone"
  | "wood"
  | "glass"
  | "dirt"
  | "water"
  | "wool"
  | "light"
  | "leaves"
  | "sand"
  | "brick";

interface BlockRecord {
  bot: string;
  type: BlockType;
  label?: string;
  ts?: string;
}

interface PlayerRecord {
  color: string;
  block_count: number;
}

interface TurnLogEntry {
  actor: string;
  ts: string;
  action: string;
  args?: Record<string, unknown>;
  reasoning?: string | null;
  summary?: string | null;
}

interface BlockyardState {
  game_type?: string;
  phase?: GamePhase;
  participants?: string[];
  last_actor?: string | null;
  round?: number;
  turn_log?: TurnLogEntry[];
  bounds?: { x?: number; y?: number; z?: number };
  blocks?: Record<string, BlockRecord>;
  players?: Record<string, PlayerRecord>;
  blocks_per_turn?: number;
}

const ACTOR_USER = "__user__";

const BLOCK_TYPES: BlockType[] = [
  "stone",
  "wood",
  "glass",
  "dirt",
  "water",
  "wool",
  "light",
  "leaves",
  "sand",
  "brick",
];

// Per-block surface colors. Tuple is [top, left-face, right-face] so the
// isometric cube reads with shading. Hand-tuned to keep readability against
// both light and dark canvas backgrounds.
const BLOCK_SKIN: Record<BlockType, { top: string; left: string; right: string; emoji: string; label: string; alpha?: number }> = {
  stone:  { top: "#a8a8ac", left: "#76767a", right: "#5e5e62", emoji: "🪨", label: "Stone" },
  wood:   { top: "#a87044", left: "#7d4f2c", right: "#5d3a1f", emoji: "🪵", label: "Wood" },
  glass:  { top: "#c9eaf6", left: "#9ec7d8", right: "#7eafc4", emoji: "🔷", label: "Glass", alpha: 0.55 },
  dirt:   { top: "#7a5232", left: "#553820", right: "#3c2613", emoji: "🟫", label: "Dirt" },
  water:  { top: "#5cabe8", left: "#3a82c2", right: "#235e9b", emoji: "💧", label: "Water", alpha: 0.7 },
  wool:   { top: "#ececec", left: "#bcbcbc", right: "#9c9c9c", emoji: "🧶", label: "Wool" },
  light:  { top: "#ffe8a0", left: "#e6c875", right: "#caa752", emoji: "💡", label: "Light" },
  leaves: { top: "#5fa658", left: "#43803c", right: "#2e602c", emoji: "🍃", label: "Leaves" },
  sand:   { top: "#e6cf95", left: "#bba36b", right: "#998148", emoji: "🟨", label: "Sand" },
  brick:  { top: "#c45a48", left: "#933e30", right: "#702a20", emoji: "🧱", label: "Brick" },
};

// ── Procedural helpers ───────────────────────────────────────────────────

function hash32(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

function makeRng(seed: string) {
  let state = hash32(seed) || 1;
  return () => {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface AtmStar { x: number; y: number; r: number; o: number; phase: number }

function atmosphereStars(seed: string, count = 60): AtmStar[] {
  const rand = makeRng(seed);
  const out: AtmStar[] = [];
  for (let i = 0; i < count; i++) {
    out.push({
      x: rand() * 100,
      y: rand() * 100,
      r: 0.18 + rand() * 0.22,
      o: 0.25 + rand() * 0.55,
      phase: rand() * 6,
    });
  }
  return out;
}

// Isometric projection. (gx, gy, gz) — grid coordinates where
// +x runs east, +y runs south, +z runs up. Returns SVG coords on the
// 400×340 viewBox declared on the main <svg>. Origin sits high enough
// that an 8-tall stack at corner (0,0) clears the top edge AND the full
// 16×16 ground diamond + asteroid hang stay inside the bottom.
const TILE_W = 12;
const TILE_H = 6;
const TILE_Z = 12;
const ORIGIN_X = 200;
const ORIGIN_Y = 100;

function iso(x: number, y: number, z: number): [number, number] {
  return [
    ORIGIN_X + (x - y) * TILE_W,
    ORIGIN_Y + (x + y) * TILE_H - z * TILE_Z,
  ];
}

// Cube faces: top diamond, left rhombus, right rhombus. Returns three
// polygon point strings.
function cubeFaces(x: number, y: number, z: number): { top: string; left: string; right: string } {
  // 8 corners of the cube
  const tl = iso(x, y, z + 1);          // top-left (north corner of top)
  const tr = iso(x + 1, y, z + 1);      // top-right (east corner of top)
  const tb = iso(x + 1, y + 1, z + 1);  // top-bottom (south corner)
  const tl2 = iso(x, y + 1, z + 1);     // top-left2 (west corner of top)
  const bl = iso(x, y + 1, z);          // bottom-left (west corner of bottom)
  const bb = iso(x + 1, y + 1, z);      // bottom-bottom (south corner of bottom)
  const br = iso(x + 1, y, z);          // bottom-right (east corner of bottom)
  // Top face — 4 corners of the upper diamond
  const top = `${tl[0]},${tl[1]} ${tr[0]},${tr[1]} ${tb[0]},${tb[1]} ${tl2[0]},${tl2[1]}`;
  // Left face — west wall (visible from camera)
  const left = `${tl2[0]},${tl2[1]} ${tb[0]},${tb[1]} ${bb[0]},${bb[1]} ${bl[0]},${bl[1]}`;
  // Right face — south wall
  const right = `${tb[0]},${tb[1]} ${tr[0]},${tr[1]} ${br[0]},${br[1]} ${bb[0]},${bb[1]}`;
  return { top, left, right };
}

// Asteroid silhouette beneath the building plane — soft elliptical hang
// that anchors the floating world. No grid clipping needed since blocks
// always sit on or above z=0.
function asteroidPath(seed: string, gridSize: number): string {
  const rand = makeRng(`${seed}-rock`);
  const [tlx, tly] = iso(0, 0, 0);
  const [trx, try_] = iso(gridSize, 0, 0);
  const [bbx, bby] = iso(gridSize, gridSize, 0);
  const [blx, bly] = iso(0, gridSize, 0);
  // Top diamond corners — these become the "land surface" rim.
  const segments = 9;
  const pts: Array<[number, number]> = [];
  // right → bottom
  for (let i = 1; i <= segments; i++) {
    const t = i / (segments + 1);
    const baseX = trx + (bbx - trx) * t;
    const baseY = try_ + (bby - try_) * t;
    const hang = 28 * (0.5 + Math.sin(t * Math.PI));
    const jx = (rand() - 0.5) * 8;
    const jy = (rand() - 0.5) * 6;
    pts.push([baseX + jx, baseY + hang + jy]);
  }
  pts.push([bbx + (rand() - 0.5) * 6, bby + 36 + rand() * 6]);
  for (let i = 1; i <= segments; i++) {
    const t = i / (segments + 1);
    const baseX = bbx + (blx - bbx) * t;
    const baseY = bby + (bly - bby) * t;
    const hang = 28 * (0.5 + Math.sin((1 - t) * Math.PI));
    const jx = (rand() - 0.5) * 8;
    const jy = (rand() - 0.5) * 6;
    pts.push([baseX + jx, baseY + hang + jy]);
  }
  const parts: string[] = [];
  parts.push(`M ${tlx.toFixed(1)} ${tly.toFixed(1)}`);
  parts.push(`L ${trx.toFixed(1)} ${try_.toFixed(1)}`);
  for (let i = 0; i < pts.length; i++) {
    const cur = pts[i];
    const next = pts[i + 1];
    if (next) {
      const mx = (cur[0] + next[0]) / 2;
      const my = (cur[1] + next[1]) / 2;
      parts.push(`Q ${cur[0].toFixed(1)} ${cur[1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`);
    } else {
      parts.push(`Q ${cur[0].toFixed(1)} ${cur[1].toFixed(1)} ${blx.toFixed(1)} ${bly.toFixed(1)}`);
    }
  }
  parts.push("Z");
  return parts.join(" ");
}

// Top diamond points — the "ground plane" of the build area.
function groundDiamond(gridSize: number): string {
  const a = iso(0, 0, 0);
  const b = iso(gridSize, 0, 0);
  const c = iso(gridSize, gridSize, 0);
  const d = iso(0, gridSize, 0);
  return `${a[0]},${a[1]} ${b[0]},${b[1]} ${c[0]},${c[1]} ${d[0]},${d[1]}`;
}

// ── Component ────────────────────────────────────────────────────────────

export function BlockyardWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/game_blockyard",
    channelId,
    dashboardPinId,
  );
  const widgetInstanceId = currentPayload.widget_instance_id;
  const state = (currentPayload.state ?? {}) as BlockyardState;
  const phase: GamePhase = state.phase ?? "setup";
  const bounds = {
    x: state.bounds?.x ?? 16,
    y: state.bounds?.y ?? 16,
    z: state.bounds?.z ?? 8,
  };
  const blocks = state.blocks ?? {};
  const players = state.players ?? {};
  const participants = state.participants ?? [];
  const turnLog = state.turn_log ?? [];
  const round = state.round ?? 0;
  const lastActor = state.last_actor ?? null;

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedType, setSelectedType] = useState<BlockType>("stone");
  const [hoverCell, setHoverCell] = useState<{ x: number; y: number; z: number } | null>(null);
  const [removeMode, setRemoveMode] = useState(false);

  const seed = dashboardPinId ?? widgetInstanceId ?? "blockyard";
  const gridSize = bounds.x; // assume square for the asteroid base
  const asteroidD = useMemo(() => asteroidPath(seed, gridSize), [seed, gridSize]);
  const groundD = useMemo(() => groundDiamond(gridSize), [gridSize]);
  const atmStars = useMemo(() => atmosphereStars(seed, 60), [seed]);

  const { data: bots } = useBots();
  const botById = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    (bots ?? []).forEach((b) => map.set(b.id, { id: b.id, name: b.name ?? b.id }));
    return map;
  }, [bots]);
  const availableBots = useMemo(() => Array.from(botById.values()), [botById]);

  // Sort blocks by (x + y, z) for painter's algorithm — back rows first,
  // bottom layers first within a row. This gives correct occlusion in iso
  // projection without z-buffering.
  const sortedBlocks = useMemo(() => {
    const list: Array<{ x: number; y: number; z: number; block: BlockRecord }> = [];
    for (const [k, v] of Object.entries(blocks)) {
      const [x, y, z] = k.split(",").map(Number);
      if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) {
        list.push({ x, y, z, block: v });
      }
    }
    // Render order: deeper iso depth (x+y) first, lower z first.
    list.sort((a, b) => {
      const da = a.x + a.y;
      const db = b.x + b.y;
      if (da !== db) return da - db;
      return a.z - b.z;
    });
    return list;
  }, [blocks]);

  // Top-of-stack helper — the highest z occupied at (x, y), or -1 if empty.
  const heightMap = useMemo(() => {
    const map: Record<string, number> = {};
    for (const { x, y, z } of sortedBlocks) {
      const k = `${x},${y}`;
      const cur = map[k] ?? -1;
      if (z > cur) map[k] = z;
    }
    return map;
  }, [sortedBlocks]);

  if (!widgetInstanceId) {
    return (
      <PreviewCard
        title="Blockyard"
        description="Collaborative voxel-stacking on a shared 3D grid. Pin to begin."
        t={t}
      />
    );
  }

  async function runAction(action: string, args: Record<string, unknown>, busyKey = action) {
    setBusy(busyKey);
    setError(null);
    try {
      await dispatchNativeAction(action, args);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  function toggleParticipant(botId: string) {
    const next = participants.includes(botId)
      ? participants.filter((id) => id !== botId)
      : [...participants, botId];
    void runAction("set_participants", { bot_ids: next });
  }

  function userPlace(x: number, y: number, z: number) {
    void runAction("place", { x, y, z, type: selectedType });
  }

  function userRemove(x: number, y: number, z: number) {
    void runAction("remove", { x, y, z });
  }

  function handleCellClick(x: number, y: number) {
    if (phase === "ended") return;
    const top = heightMap[`${x},${y}`] ?? -1;
    if (removeMode) {
      if (top < 0) return;
      userRemove(x, y, top);
      return;
    }
    const z = top + 1;
    if (z >= bounds.z) {
      setError(`Already at max height (${bounds.z}) at (${x},${y}).`);
      return;
    }
    userPlace(x, y, z);
  }

  // Players actor meta — used by GameTurnLogSection.
  const actorMeta = useMemo(() => {
    const out: Record<string, { name?: string; color?: string }> = {};
    for (const id of participants) {
      out[id] = { name: botById.get(id)?.name, color: players[id]?.color };
    }
    return out;
  }, [participants, players, botById]);

  // Map players → species-shaped record so GameParticipantsSection can render
  // the picker with the right colors/emoji without us forking the component.
  const speciesByBotId = useMemo(() => {
    const map: Record<string, { color?: string; emoji?: string; food?: number }> = {};
    for (const [botId, player] of Object.entries(players)) {
      map[botId] = {
        color: player.color,
        emoji: "▣",
        food: player.block_count,
      };
    }
    return map;
  }, [players]);

  // Hover preview block (only on the ground click overlay)
  const hoverPreview = hoverCell;

  return (
    // `pointer-events-none` on the wrapper so the empty rectangle around
    // the floating asteroid stays click-through to the canvas under us.
    // Re-enabled per-element on the actual map shapes + chrome below.
    <div className="blockyard-stage group/blockyard relative flex w-full h-full min-h-0 overflow-hidden pointer-events-none">
      {/* Atmosphere halo */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(80% 60% at 50% 45%, var(--by-bg-inner) 0%, var(--by-bg-mid) 55%, var(--by-bg-outer) 100%)",
        }}
      />
      {/* Atmospheric glitter */}
      <svg
        aria-hidden
        className="absolute inset-0 w-full h-full pointer-events-none"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
      >
        {atmStars.map((s, i) => (
          <circle
            key={i}
            cx={s.x}
            cy={s.y}
            r={s.r * 0.32}
            fill="var(--by-star)"
            opacity={s.o}
            className="blockyard-atm-star"
            style={{ animationDelay: `${s.phase}s` }}
          />
        ))}
      </svg>

      {/* ── Main stage ─────────────────────────────────────────── */}
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 400 340"
        preserveAspectRatio="xMidYMid meet"
        style={{ pointerEvents: "none" }}
      >
        <defs>
          <radialGradient id={`by-ground-${widgetInstanceId}`} cx="0.5" cy="0.4" r="0.7">
            <stop offset="0%" stopColor="#6f5b3f" />
            <stop offset="55%" stopColor="#4d3b27" />
            <stop offset="100%" stopColor="#251a10" />
          </radialGradient>
          <linearGradient id={`by-rock-${widgetInstanceId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3a2818" />
            <stop offset="100%" stopColor="#100a06" />
          </linearGradient>
          <filter id={`by-glow-${widgetInstanceId}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="1.0" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Asteroid drifting. `pointer-events: auto` is restored on the
            map shapes themselves so the asteroid + ground + blocks +
            hit zones capture clicks while the surrounding empty SVG
            stays click-through (for canvas pan). */}
        <g className="blockyard-drift" style={{ transformOrigin: "200px 170px", pointerEvents: "auto" }}>
          {/* Underside silhouette */}
          <path d={asteroidD} fill={`url(#by-rock-${widgetInstanceId})`} />
          <path d={asteroidD} fill="none" stroke="rgba(170, 200, 255, 0.18)" strokeWidth="0.6" />

          {/* Ground plane */}
          <polygon points={groundD} fill={`url(#by-ground-${widgetInstanceId})`} />
          {/* Subtle iso grid lines on ground */}
          <g opacity="0.10" stroke="#fff8dc" strokeWidth="0.25">
            {Array.from({ length: gridSize - 1 }, (_, i) => i + 1).map((i) => {
              const a = iso(i, 0, 0);
              const b = iso(i, gridSize, 0);
              return <line key={`gx-${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />;
            })}
            {Array.from({ length: gridSize - 1 }, (_, i) => i + 1).map((i) => {
              const a = iso(0, i, 0);
              const b = iso(gridSize, i, 0);
              return <line key={`gy-${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />;
            })}
          </g>

          {/* Hover preview cube — drawn before real blocks so real ones can occlude it
              when the user hovers a stack location. */}
          {hoverPreview && !removeMode && phase !== "ended" && (() => {
            const { x, y } = hoverPreview;
            const top = heightMap[`${x},${y}`] ?? -1;
            const z = top + 1;
            if (z >= bounds.z) return null;
            const skin = BLOCK_SKIN[selectedType];
            const f = cubeFaces(x, y, z);
            return (
              <g opacity={0.55} className="pointer-events-none">
                <polygon points={f.left} fill={skin.left} />
                <polygon points={f.right} fill={skin.right} />
                <polygon points={f.top} fill={skin.top} stroke="#fff" strokeWidth="0.5" strokeOpacity={0.7} />
              </g>
            );
          })()}

          {/* Blocks */}
          <g>
            {sortedBlocks.map(({ x, y, z, block }) => {
              const skin = BLOCK_SKIN[block.type] ?? BLOCK_SKIN.stone;
              const f = cubeFaces(x, y, z);
              const playerColor = players[block.bot]?.color;
              const isLight = block.type === "light";
              const isGlass = block.type === "glass";
              const alpha = skin.alpha ?? 1;
              return (
                <g key={`b-${x}-${y}-${z}`} opacity={alpha} style={{ cursor: removeMode ? "pointer" : "default" }}
                   onClick={(e) => {
                     if (removeMode) {
                       e.stopPropagation();
                       userRemove(x, y, z);
                     }
                   }}
                >
                  <title>{`${skin.label} at (${x},${y},${z})${block.label ? ` — ${block.label}` : ""} · placed by ${block.bot === ACTOR_USER ? "you" : (botById.get(block.bot)?.name ?? block.bot)}`}</title>
                  <polygon points={f.left} fill={skin.left} stroke="rgba(0,0,0,0.25)" strokeWidth={0.3} />
                  <polygon points={f.right} fill={skin.right} stroke="rgba(0,0,0,0.25)" strokeWidth={0.3} />
                  <polygon points={f.top} fill={skin.top} stroke="rgba(0,0,0,0.18)" strokeWidth={0.3} />
                  {/* Owner stripe along top-front edge */}
                  {playerColor && (
                    <polyline
                      points={(() => {
                        const a = iso(x + 1, y, z + 1);
                        const b = iso(x + 1, y + 1, z + 1);
                        return `${a[0]},${a[1]} ${b[0]},${b[1]}`;
                      })()}
                      stroke={playerColor}
                      strokeWidth={0.8}
                      opacity={0.85}
                    />
                  )}
                  {/* Light blocks — soft glow halo on top */}
                  {isLight && (() => {
                    const center = iso(x + 0.5, y + 0.5, z + 1);
                    return (
                      <circle
                        cx={center[0]}
                        cy={center[1]}
                        r={6}
                        fill="#fff7c8"
                        opacity={0.55}
                        filter={`url(#by-glow-${widgetInstanceId})`}
                      />
                    );
                  })()}
                  {/* Glass — diagonal highlight on top */}
                  {isGlass && (() => {
                    const a = iso(x, y, z + 1);
                    const b = iso(x + 1, y + 1, z + 1);
                    return (
                      <line
                        x1={a[0] + 1}
                        y1={a[1] + 1}
                        x2={b[0] - 1}
                        y2={b[1] - 1}
                        stroke="#fff"
                        strokeWidth={0.5}
                        opacity={0.7}
                      />
                    );
                  })()}
                  {/* Label flag — only render the topmost-z occurrence per (x,y) so
                      stacked towers don't pile labels. */}
                  {block.label && (heightMap[`${x},${y}`] === z) && (() => {
                    const top = iso(x + 0.5, y + 0.5, z + 1);
                    return (
                      <g transform={`translate(${top[0]} ${top[1] - 4})`}>
                        <rect
                          x={-(Math.min(block.label.length, 14) * 1.7) - 2}
                          y={-4}
                          width={Math.min(block.label.length, 14) * 3.4 + 4}
                          height={6.2}
                          rx={1.6}
                          fill="rgba(0,0,0,0.55)"
                        />
                        <text
                          x={0}
                          y={0.5}
                          fontSize={3.4}
                          textAnchor="middle"
                          fill="#fff"
                        >
                          {block.label.length > 14 ? `${block.label.slice(0, 13)}…` : block.label}
                        </text>
                      </g>
                    );
                  })()}
                </g>
              );
            })}
          </g>

          {/* Click hit zones on the ground — one diamond per (x, y) cell.
              Always present on top of blocks so users can click to stack. */}
          <g>
            {Array.from({ length: gridSize }, (_, y) =>
              Array.from({ length: gridSize }, (_, x) => {
                const top = heightMap[`${x},${y}`] ?? -1;
                const targetZ = removeMode ? Math.max(top, 0) : top + 1;
                const center = iso(x + 0.5, y + 0.5, targetZ);
                // Diamond hit polygon at the click target plane
                const a = iso(x, y, targetZ);
                const b = iso(x + 1, y, targetZ);
                const c = iso(x + 1, y + 1, targetZ);
                const d = iso(x, y + 1, targetZ);
                return (
                  <polygon
                    key={`hit-${x}-${y}`}
                    points={`${a[0]},${a[1]} ${b[0]},${b[1]} ${c[0]},${c[1]} ${d[0]},${d[1]}`}
                    fill="rgba(255,255,255,0.001)"
                    stroke="transparent"
                    style={{ cursor: phase === "ended" ? "default" : "pointer" }}
                    onPointerEnter={() => setHoverCell({ x, y, z: targetZ })}
                    onPointerLeave={() => setHoverCell((c) => (c?.x === x && c?.y === y ? null : c))}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCellClick(x, y);
                    }}
                    aria-label={`cell ${x},${y} (top z=${top})`}
                    transform={center ? undefined : undefined}
                  />
                );
              }),
            )}
          </g>
        </g>
      </svg>

      {/* ── Floating chrome — bottom-left HUD ───────────────────── */}
      <div className="absolute bottom-2 left-2 flex flex-row items-center gap-1.5 px-2 py-1 rounded-full text-[10px] tracking-wide bg-black/35 backdrop-blur-md text-white/85 border border-white/10 opacity-25 group-hover/blockyard:opacity-100 transition-opacity duration-300 pointer-events-none">
        <span>🧱</span>
        <span className="uppercase font-semibold tracking-wider">{phase}</span>
        <span className="text-white/40">·</span>
        <span>r{round}</span>
        <span className="text-white/40">·</span>
        <span>{Object.keys(blocks).length} blocks</span>
        {lastActor && (
          <>
            <span className="text-white/40">·</span>
            <span className="text-white/60">{lastActor === ACTOR_USER ? "you" : (botById.get(lastActor)?.name ?? lastActor)}</span>
          </>
        )}
      </div>

      {/* Settings gear */}
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          setSettingsOpen(true);
        }}
        className="absolute top-2 left-2 z-20 w-7 h-7 rounded-full bg-black/30 backdrop-blur-md text-white/70 border border-white/10 flex items-center justify-center opacity-30 hover:opacity-100 group-hover/blockyard:opacity-90 hover:bg-black/55 transition-all duration-300 pointer-events-auto"
        title="Game settings"
      >
        <Settings size={12} />
      </button>

      {/* Block palette — top-right, always visible during play. The user is
          a first-class player; they need a fast block picker without going
          through settings. */}
      {phase !== "ended" && (
        <div
          className="absolute top-2 right-2 z-10 flex flex-col gap-1 p-1 rounded-md bg-black/35 backdrop-blur-md border border-white/10 opacity-50 group-hover/blockyard:opacity-100 transition-opacity pointer-events-auto"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => setRemoveMode((v) => !v)}
            className="w-7 h-7 rounded text-[14px] flex items-center justify-center transition-colors"
            style={{
              background: removeMode ? "rgba(220,90,80,0.6)" : "rgba(255,255,255,0.06)",
              color: removeMode ? "#fff" : "#e5e5e5",
            }}
            title={removeMode ? "Remove mode (click cancel to exit)" : "Switch to remove mode"}
          >
            {removeMode ? "✕" : "🗑"}
          </button>
          <div className="h-px w-full bg-white/10 my-0.5" />
          {BLOCK_TYPES.map((bt) => {
            const skin = BLOCK_SKIN[bt];
            const active = !removeMode && selectedType === bt;
            return (
              <button
                key={bt}
                type="button"
                onClick={() => {
                  setSelectedType(bt);
                  setRemoveMode(false);
                }}
                className="w-7 h-7 rounded flex items-center justify-center text-[12px] transition-all"
                style={{
                  background: active ? `${skin.top}cc` : "rgba(255,255,255,0.06)",
                  outline: active ? `1px solid ${skin.top}` : "none",
                }}
                title={skin.label}
              >
                {skin.emoji}
              </button>
            );
          })}
        </div>
      )}

      {/* Setup hint */}
      {phase === "setup" && participants.length === 0 && (
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full text-[11px] bg-black/55 backdrop-blur-md text-white/90 border border-white/15 flex items-center gap-1.5 hover:bg-black/70 transition-colors pointer-events-auto"
        >
          <Plus size={12} />
          Add bots to begin
          <ChevronRight size={12} className="opacity-60" />
        </button>
      )}

      {/* Inline error / busy chips */}
      {error && (
        <div className="absolute top-12 right-12 max-w-[60%] px-2 py-1 rounded-md text-[10px] bg-danger/30 text-danger border border-danger/40 backdrop-blur-md">
          {error}
        </div>
      )}
      {busy && !settingsOpen && (
        <div className="absolute top-12 right-12 px-2 py-1 rounded-md text-[10px] bg-black/50 backdrop-blur-md text-white/70">
          …
        </div>
      )}

      {/* ── Settings drawer ──────────────────────────────────── */}
      <WidgetSettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        kicker="Blockyard"
        title={
          phase === "setup"
            ? "Setup"
            : phase === "playing"
              ? `Playing · round ${round}`
              : "Ended"
        }
      >
        <GameParticipantsSection
          bots={availableBots}
          participants={participants}
          speciesByBotId={speciesByBotId}
          onToggle={toggleParticipant}
          defaultEmoji="▣"
          defaultColor="#c8a45a"
        />

        <GamePhaseSection
          phase={phase}
          participantCount={participants.length}
          busy={busy === "set_phase"}
          startLabel="Start building"
          onSetPhase={(next) => void runAction("set_phase", { phase: next })}
          onAdvanceRound={() => void runAction("advance_round", {})}
        />

        {/* Bounds + stats */}
        <WidgetSettingsSection label="World">
          <div className="text-[11px] text-text-dim grid grid-cols-2 gap-1">
            <span>Bounds</span>
            <span className="font-mono text-text">{bounds.x}×{bounds.y}×{bounds.z}</span>
            <span>Total blocks</span>
            <span className="font-mono text-text">{Object.keys(blocks).length}</span>
            <span>Block types</span>
            <span className="font-mono text-text">{BLOCK_TYPES.length}</span>
          </div>
        </WidgetSettingsSection>

        {/* Player color overrides — only when there's anyone to color */}
        {participants.length > 0 && (
          <WidgetSettingsSection label="Player colors">
            <div className="flex flex-col gap-1">
              {participants.map((id) => {
                const player = players[id];
                if (!player) return null;
                const name = botById.get(id)?.name ?? id;
                return (
                  <div
                    key={id}
                    className="flex items-center gap-2 px-2 py-1 rounded border border-surface-border bg-surface"
                  >
                    <span
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ background: player.color }}
                    />
                    <span className="text-[12px] flex-1 truncate">{name}</span>
                    <span className="text-[10px] text-text-dim font-mono">{player.block_count}</span>
                    <input
                      type="color"
                      value={player.color}
                      onChange={(e) =>
                        void runAction(
                          "set_player_color",
                          { bot_id: id, color: e.target.value },
                          `color-${id}`,
                        )
                      }
                      className="w-6 h-6 rounded cursor-pointer bg-transparent border-0 p-0"
                      title="Change color"
                    />
                  </div>
                );
              })}
            </div>
          </WidgetSettingsSection>
        )}

        {/* Maintenance */}
        {phase !== "setup" && (
          <WidgetSettingsSection label="World maintenance">
            <button
              type="button"
              onClick={() => void runAction("clear_blocks", {})}
              className="px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface text-text-dim hover:text-text"
              disabled={busy === "clear_blocks"}
            >
              Clear all blocks…
            </button>
          </WidgetSettingsSection>
        )}

        <GameTurnLogSection log={turnLog} actorMeta={actorMeta} />
      </WidgetSettingsDrawer>

      <style>{`
        .blockyard-stage {
          --by-bg-inner: rgba(220, 232, 255, 0.10);
          --by-bg-mid: rgba(200, 218, 245, 0.04);
          --by-bg-outer: rgba(200, 218, 245, 0);
          --by-star: #5a78c8;
        }
        :root.dark .blockyard-stage,
        .dark .blockyard-stage {
          --by-bg-inner: rgba(40, 40, 80, 0.18);
          --by-bg-mid: rgba(20, 20, 40, 0.08);
          --by-bg-outer: rgba(10, 10, 25, 0);
          --by-star: #dfe7ff;
        }
        @keyframes blockyard-atm-twinkle {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 0.95; }
        }
        .blockyard-atm-star {
          animation: blockyard-atm-twinkle 4s ease-in-out infinite;
        }
        @keyframes blockyard-drift {
          0% { transform: translate(0, 0) rotate(0deg); }
          100% { transform: translate(0.8px, -1.2px) rotate(0.3deg); }
        }
        .blockyard-drift {
          animation: blockyard-drift 16s ease-in-out infinite alternate;
        }
        @media (prefers-reduced-motion: reduce) {
          .blockyard-drift, .blockyard-atm-star {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  );
}
