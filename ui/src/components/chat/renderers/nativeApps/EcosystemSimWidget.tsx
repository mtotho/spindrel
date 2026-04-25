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

type EcosystemPhase = GamePhase;

interface SpeciesRecord {
  emoji: string;
  color: string;
  traits: string[];
  food: number;
}

interface CellRecord {
  owner: string;
  food: number;
}

interface FoodSource {
  x: number;
  y: number;
  amount: number;
}

interface TurnLogEntry {
  actor: string;
  ts: string;
  action: string;
  args?: Record<string, unknown>;
  reasoning?: string | null;
  summary?: string | null;
}

interface EcosystemState {
  game_type?: string;
  phase?: EcosystemPhase;
  participants?: string[];
  last_actor?: string | null;
  round?: number;
  turn_log?: TurnLogEntry[];
  board?: { size?: number; cells?: (CellRecord | null)[][] };
  species?: Record<string, SpeciesRecord>;
  environment?: { weather?: string; food_sources?: FoodSource[] };
}

const BOARD_SIZE = 12;

// ── Procedural helpers ────────────────────────────────────────────────────

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

function atmosphereStars(seed: string, count = 75): AtmStar[] {
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

// Isometric projection of grid (x, y) into SVG coords on the 200×140 viewBox.
const ISO_CX = 100;
const ISO_CY = 36;
const ISO_TILE_W = 7;
const ISO_TILE_H = 3.6;
const ISO_DEPTH = 22;

function iso(x: number, y: number): [number, number] {
  return [
    ISO_CX + (x - y) * (ISO_TILE_W / 2),
    ISO_CY + (x + y) * (ISO_TILE_H / 2),
  ];
}

// Asteroid silhouette: irregular bottom edge below the iso plane so the
// platform reads as a chunk of rock floating in space, not a clean diamond.
function asteroidPath(seed: string): string {
  const rand = makeRng(seed);
  const [tx, ty] = iso(0, 0);              // top point
  const [rx, ry] = iso(BOARD_SIZE - 1, 0); // right point
  const [bx, by] = iso(BOARD_SIZE - 1, BOARD_SIZE - 1); // bottom point
  const [lx, ly] = iso(0, BOARD_SIZE - 1); // left point

  const depthRight: number[] = [];
  const depthLeft: number[] = [];
  const segments = 7;
  for (let i = 0; i < segments; i++) {
    depthRight.push(ISO_DEPTH * (0.6 + rand() * 0.8));
    depthLeft.push(ISO_DEPTH * (0.6 + rand() * 0.8));
  }

  const path: string[] = [];
  // Top contour: top → right → bottom → left → close
  path.push(`M ${tx.toFixed(1)} ${ty.toFixed(1)}`);
  path.push(`L ${rx.toFixed(1)} ${ry.toFixed(1)}`);
  // Drop down right side jaggedly to bottom corner
  for (let i = 0; i < segments; i++) {
    const t = (i + 1) / segments;
    const sx = rx + (bx - rx) * t;
    const sy = ry + (by - ry) * t + depthRight[i];
    path.push(`L ${sx.toFixed(1)} ${sy.toFixed(1)}`);
  }
  // Climb back up left side jaggedly to left corner
  for (let i = segments - 1; i >= 0; i--) {
    const t = i / segments;
    const sx = lx + (bx - lx) * t;
    const sy = ly + (by - ly) * t + depthLeft[i];
    path.push(`L ${sx.toFixed(1)} ${sy.toFixed(1)}`);
  }
  path.push(`L ${lx.toFixed(1)} ${ly.toFixed(1)}`);
  path.push("Z");
  return path.join(" ");
}

// Top diamond as a polygon (4 iso corners).
function topDiamondPoints(): string {
  const [tx, ty] = iso(0, 0);
  const [rx, ry] = iso(BOARD_SIZE - 1, 0);
  const [bx, by] = iso(BOARD_SIZE - 1, BOARD_SIZE - 1);
  const [lx, ly] = iso(0, BOARD_SIZE - 1);
  return `${tx},${ty} ${rx},${ry} ${bx},${by} ${lx},${ly}`;
}

const WEATHER_TINTS: Record<string, { tint: string; sky: string; label: string; emoji: string }> = {
  neutral: { tint: "transparent", sky: "rgba(40, 50, 90, 0.0)", label: "Neutral", emoji: "🌑" },
  drought: { tint: "rgba(220, 130, 50, 0.32)", sky: "rgba(180, 90, 40, 0.18)", label: "Drought", emoji: "☀️" },
  flood:   { tint: "rgba(80, 140, 220, 0.34)", sky: "rgba(60, 110, 200, 0.18)", label: "Flood", emoji: "🌊" },
  bloom:   { tint: "rgba(120, 200, 90, 0.30)", sky: "rgba(110, 200, 110, 0.18)", label: "Bloom", emoji: "🌸" },
};

// ── Component ─────────────────────────────────────────────────────────────

export function EcosystemSimWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/game_ecosystem",
    channelId,
    dashboardPinId,
  );
  const widgetInstanceId = currentPayload.widget_instance_id;
  const state = (currentPayload.state ?? {}) as EcosystemState;
  const phase: EcosystemPhase = state.phase ?? "setup";
  const board = state.board?.cells ?? Array.from({ length: BOARD_SIZE }, () => Array<CellRecord | null>(BOARD_SIZE).fill(null));
  const species = state.species ?? {};
  const participants = state.participants ?? [];
  const turnLog = state.turn_log ?? [];
  const env = state.environment ?? { weather: "neutral", food_sources: [] };
  const round = state.round ?? 0;
  const lastActor = state.last_actor ?? null;
  const foodSources = env.food_sources ?? [];
  const weather = env.weather ?? "neutral";
  const weatherSkin = WEATHER_TINTS[weather] ?? WEATHER_TINTS.neutral;

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [placeFoodMode, setPlaceFoodMode] = useState(false);

  const seed = dashboardPinId ?? widgetInstanceId ?? "asteroid";
  const asteroidD = useMemo(() => asteroidPath(seed), [seed]);
  const atmStars = useMemo(() => atmosphereStars(seed, 75), [seed]);
  const topD = useMemo(() => topDiamondPoints(), []);

  const { data: bots } = useBots();
  const botById = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    (bots ?? []).forEach((b) => map.set(b.id, { id: b.id, name: b.name ?? b.id }));
    return map;
  }, [bots]);
  const availableBots = useMemo(
    () => Array.from(botById.values()),
    [botById],
  );

  if (!widgetInstanceId) {
    return (
      <PreviewCard
        title="Ecosystem Sim"
        description="A floating asteroid where bots evolve species. Pin to begin."
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

  function setWeather(w: string) {
    void runAction("set_environment", { weather: w });
  }

  function placeFoodAt(x: number, y: number) {
    const next = [...foodSources, { x, y, amount: 2 }];
    void runAction("set_environment", { food_sources: next });
    setPlaceFoodMode(false);
  }

  function clearFoodAt(x: number, y: number) {
    const next = foodSources.filter((src) => !(src.x === x && src.y === y));
    void runAction("set_environment", { food_sources: next });
  }

  // Sparse list of owned cells with iso coords for SVG.
  const cells: Array<{ x: number; y: number; cell: CellRecord; sx: number; sy: number }> = [];
  for (let y = 0; y < BOARD_SIZE; y++) {
    for (let x = 0; x < BOARD_SIZE; x++) {
      const cell = board[y]?.[x];
      if (cell) {
        const [sx, sy] = iso(x, y);
        cells.push({ x, y, cell, sx, sy });
      }
    }
  }

  // Bot avatar positions — anchor on the species' first owned cell so the
  // little character stands on the patch they grew. Falls back to the seed
  // location if the bot has no cells yet (setup phase).
  const botAvatars: Array<{ botId: string; sx: number; sy: number; species: SpeciesRecord; phase: number }> = [];
  for (const botId of participants) {
    const sp = species[botId];
    if (!sp) continue;
    const owned = cells.filter((c) => c.cell.owner === botId);
    let sx = 0;
    let sy = 0;
    if (owned.length > 0) {
      sx = owned.reduce((a, c) => a + c.sx, 0) / owned.length;
      sy = owned.reduce((a, c) => a + c.sy, 0) / owned.length;
    } else {
      const h = hash32(botId);
      const x = h % BOARD_SIZE;
      const y = (h >> 8) % BOARD_SIZE;
      const [px, py] = iso(x, y);
      sx = px;
      sy = py;
    }
    botAvatars.push({
      botId,
      sx,
      sy,
      species: sp,
      phase: (hash32(botId) % 1000) / 1000,
    });
  }

  return (
    <div className="ecosystem-stage group/ecosystem relative flex w-full h-full min-h-0 overflow-hidden">
      {/* Atmosphere — a soft radial halo that sits ON TOP of the canvas
          backdrop. In dark mode it reads as deeper space; in light mode it
          reads as a luminous near-white halo so the asteroid still has
          presence against the cream canvas. Color comes from CSS variables
          declared on `.ecosystem-stage` and overridden under `:root.dark`. */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(80% 60% at 50% 45%, var(--eco-bg-inner) 0%, var(--eco-bg-mid) 55%, var(--eco-bg-outer) 100%)",
        }}
      />
      {/* Weather glow — soft tint at the asteroid's center */}
      {weatherSkin.tint !== "transparent" && (
        <div
          aria-hidden
          className="absolute inset-0 ecosystem-nebula pointer-events-none mix-blend-screen"
          style={{
            background: `radial-gradient(55% 45% at 50% 55%, ${weatherSkin.sky} 0%, transparent 80%)`,
            transition: "background 1.4s ease",
          }}
        />
      )}
      {/* Atmospheric glitter — small twinkling dots that sit on top of the
          background halo. Color matches the canvas starfield in each theme.
          Density is tuned to read as "glitter" not "starfield" — only ~75 dots. */}
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
            fill="var(--eco-star)"
            opacity={s.o}
            className="ecosystem-atm-star"
            style={{ animationDelay: `${s.phase}s` }}
          />
        ))}
      </svg>

      {/* ── Main asteroid stage ──────────────────────────────────────── */}
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 200 140"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <radialGradient id={`top-${widgetInstanceId}`} cx="0.5" cy="0.4" r="0.7">
            <stop offset="0%" stopColor="#a07a5e" />
            <stop offset="55%" stopColor="#6b4f3c" />
            <stop offset="100%" stopColor="#3d2a1f" />
          </radialGradient>
          <linearGradient id={`side-${widgetInstanceId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3a2818" />
            <stop offset="100%" stopColor="#150d08" />
          </linearGradient>
          <radialGradient id={`bot-shadow-${widgetInstanceId}`} cx="0.5" cy="0.5" r="0.5">
            <stop offset="0%" stopColor="rgba(0,0,0,0.55)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0)" />
          </radialGradient>
          <filter id={`glow-${widgetInstanceId}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="0.8" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <clipPath id={`top-clip-${widgetInstanceId}`}>
            <polygon points={topD} />
          </clipPath>
        </defs>

        {/* Drop shadow under asteroid — anchors it in space */}
        <ellipse cx="100" cy="120" rx="55" ry="4.5" fill="black" opacity="0.55" filter={`url(#glow-${widgetInstanceId})`} />

        {/* Asteroid body — bobs gently */}
        <g className="ecosystem-bob" style={{ transformOrigin: "100px 70px" }}>
          {/* Side walls / underside (irregular jagged shape) */}
          <path d={asteroidD} fill={`url(#side-${widgetInstanceId})`} />
          {/* Subtle rim catch-light on the asteroid silhouette */}
          <path
            d={asteroidD}
            fill="none"
            stroke="rgba(170, 200, 255, 0.18)"
            strokeWidth="0.4"
          />

          {/* Top iso surface (the playable plane) */}
          <polygon points={topD} fill={`url(#top-${widgetInstanceId})`} />

          {/* Subtle iso grid hint on the surface — only inner lines, faint */}
          <g clipPath={`url(#top-clip-${widgetInstanceId})`} opacity="0.08" stroke="#fff8dc" strokeWidth="0.12">
            {Array.from({ length: BOARD_SIZE - 1 }, (_, i) => i + 1).map((i) => {
              const [ax, ay] = iso(i, 0);
              const [bx, by] = iso(i, BOARD_SIZE - 1);
              return <line key={`gx-${i}`} x1={ax} y1={ay} x2={bx} y2={by} />;
            })}
            {Array.from({ length: BOARD_SIZE - 1 }, (_, i) => i + 1).map((i) => {
              const [ax, ay] = iso(0, i);
              const [bx, by] = iso(BOARD_SIZE - 1, i);
              return <line key={`gy-${i}`} x1={ax} y1={ay} x2={bx} y2={by} />;
            })}
          </g>

          {/* Surface texture: scattered rock specks */}
          <g clipPath={`url(#top-clip-${widgetInstanceId})`}>
            {useMemo(() => {
              const rand = makeRng(`${seed}-specks`);
              const dots: Array<{ cx: number; cy: number; r: number; o: number }> = [];
              for (let i = 0; i < 60; i++) {
                const gx = rand() * (BOARD_SIZE - 1);
                const gy = rand() * (BOARD_SIZE - 1);
                const [sx, sy] = iso(gx, gy);
                dots.push({ cx: sx, cy: sy, r: 0.18 + rand() * 0.22, o: 0.18 + rand() * 0.18 });
              }
              return dots;
            }, [seed]).map((d, i) => (
              <circle key={i} cx={d.cx} cy={d.cy} r={d.r} fill="#e6c79c" opacity={d.o} />
            ))}
          </g>

          {/* Weather tint overlay on the surface */}
          {weatherSkin.tint !== "transparent" && (
            <polygon points={topD} fill={weatherSkin.tint} className="ecosystem-weather-overlay" />
          )}

          {/* Vegetation patches — drawn at iso position, painter's algorithm by sy */}
          <g>
            {[...cells]
              .sort((a, b) => a.sy - b.sy)
              .map(({ x, y, cell, sx, sy }) => {
                const owner = cell.owner;
                const sp = species[owner];
                const color = sp?.color ?? "#7aa2c8";
                const traits = sp?.traits ?? [];
                return (
                  <g key={`v-${x}-${y}`} transform={`translate(${sx} ${sy})`}>
                    {/* Soft ground halo */}
                    <ellipse cx="0" cy="0.5" rx="2.2" ry="1.0" fill={color} opacity={0.22} />
                    {/* Stalk */}
                    <line x1="0" y1="0" x2="0" y2={traits.includes("slow") ? -2.6 : -2} stroke={color} strokeWidth={traits.includes("slow") ? 0.6 : 0.4} />
                    {/* Bulb */}
                    <circle cx="0" cy={traits.includes("slow") ? -2.6 : -2} r={0.9} fill={color} />
                    {/* Photosynthetic — soft glow ring */}
                    {traits.includes("photosynthetic") && (
                      <circle cx="0" cy={-2} r={1.6} fill="none" stroke="#fff7c2" strokeWidth={0.18} opacity={0.65} />
                    )}
                    {/* Luminous — bright pip */}
                    {traits.includes("luminous") && (
                      <circle cx="0" cy={-2} r={0.4} fill="#fff7e0" opacity={0.95} />
                    )}
                    {/* Thorny — spikes radiating from bulb */}
                    {traits.includes("thorny") &&
                      [0, 1, 2, 3, 4].map((i) => {
                        const a = (i / 5) * Math.PI * 2;
                        return (
                          <line
                            key={i}
                            x1={Math.cos(a) * 0.9}
                            y1={-2 + Math.sin(a) * 0.9}
                            x2={Math.cos(a) * 1.5}
                            y2={-2 + Math.sin(a) * 1.5}
                            stroke={color}
                            strokeWidth={0.18}
                            opacity={0.85}
                          />
                        );
                      })}
                    {/* Aggressive — small fang triangle */}
                    {traits.includes("aggressive") && (
                      <polygon
                        points={`-0.5,-1.3 0,-2.4 0.5,-1.3`}
                        fill="#fff"
                        opacity={0.7}
                      />
                    )}
                    {/* Fast — speed lines */}
                    {traits.includes("fast") &&
                      [0, 1].map((i) => (
                        <line
                          key={i}
                          x1={1.0}
                          y1={-1.6 + i * 0.4}
                          x2={2.2}
                          y2={-1.6 + i * 0.4}
                          stroke={color}
                          strokeWidth={0.15}
                          opacity={0.55}
                        />
                      ))}
                  </g>
                );
              })}
          </g>

          {/* Food source glints */}
          <g>
            {foodSources.map((src, i) => {
              const [sx, sy] = iso(src.x, src.y);
              return (
                <g key={`food-${i}`} transform={`translate(${sx} ${sy - 0.4})`} className="ecosystem-glint">
                  <circle r={1.0} fill="#fff7c2" opacity={0.55} />
                  <circle r={0.45} fill="#ffeb88" />
                  <text textAnchor="middle" y={-1.2} fontSize="1.6" fill="#fff7c2">✦</text>
                </g>
              );
            })}
          </g>

          {/* Place-food cell hit zones — only when in placement mode */}
          {placeFoodMode && (
            <g clipPath={`url(#top-clip-${widgetInstanceId})`}>
              {Array.from({ length: BOARD_SIZE }, (_, y) =>
                Array.from({ length: BOARD_SIZE }, (_, x) => {
                  const [sx, sy] = iso(x, y);
                  const has = foodSources.find((s) => s.x === x && s.y === y);
                  const half = ISO_TILE_W / 2;
                  return (
                    <polygon
                      key={`hit-${x}-${y}`}
                      points={`${sx},${sy - ISO_TILE_H / 2} ${sx + half},${sy} ${sx},${sy + ISO_TILE_H / 2} ${sx - half},${sy}`}
                      fill="rgba(255, 247, 194, 0.10)"
                      stroke="rgba(255, 247, 194, 0.45)"
                      strokeWidth={0.12}
                      style={{ cursor: "pointer" }}
                      onClick={() => (has ? clearFoodAt(x, y) : placeFoodAt(x, y))}
                    />
                  );
                }),
              )}
            </g>
          )}

          {/* Bot characters — bobbing, rendered last so they sit on top */}
          <g>
            {botAvatars
              .sort((a, b) => a.sy - b.sy)
              .map(({ botId, sx, sy, species: sp, phase: phaseOffset }) => {
                const color = sp.color || "#7aa2c8";
                const emoji = sp.emoji || "🌱";
                return (
                  <g
                    key={`bot-${botId}`}
                    transform={`translate(${sx} ${sy})`}
                    style={{ animation: `ecosystem-walk 5.5s ease-in-out infinite`, animationDelay: `${phaseOffset * -5.5}s`, transformBox: "fill-box" }}
                  >
                    {/* contact shadow */}
                    <ellipse cx="0" cy="0.4" rx="1.6" ry="0.5" fill={`url(#bot-shadow-${widgetInstanceId})`} />
                    {/* bobbing body */}
                    <g
                      className="ecosystem-bob-body"
                      style={{ animation: `ecosystem-bob 2.2s ease-in-out infinite`, animationDelay: `${phaseOffset * -2.2}s` }}
                    >
                      {/* back foot/stalk */}
                      <ellipse cx="-0.55" cy="0" rx="0.35" ry="0.25" fill={color} opacity={0.85} />
                      <ellipse cx="0.55" cy="0" rx="0.35" ry="0.25" fill={color} opacity={0.85} />
                      {/* body */}
                      <ellipse cx="0" cy="-1.4" rx="1.55" ry="1.85" fill={color} />
                      {/* belly highlight */}
                      <ellipse cx="-0.3" cy="-1.7" rx="0.6" ry="0.85" fill="#fff" opacity={0.25} />
                      {/* eyes */}
                      <circle cx="-0.5" cy="-1.5" r="0.32" fill="#fff" />
                      <circle cx="0.55" cy="-1.5" r="0.32" fill="#fff" />
                      <circle cx="-0.4" cy="-1.45" r="0.16" fill="#0b0612" />
                      <circle cx="0.65" cy="-1.45" r="0.16" fill="#0b0612" />
                      {/* mouth — reflects "aggressive" */}
                      {sp.traits?.includes("aggressive") ? (
                        <polygon points="-0.45,-0.85 0,-0.45 0.45,-0.85" fill="#0b0612" />
                      ) : (
                        <path d="M -0.4 -0.9 Q 0 -0.65 0.4 -0.9" stroke="#0b0612" strokeWidth={0.14} fill="none" strokeLinecap="round" />
                      )}
                      {/* trait flourish on head */}
                      {sp.traits?.includes("luminous") && (
                        <circle cx="0" cy="-3.1" r="0.3" fill="#fff7e0" opacity="0.9" filter={`url(#glow-${widgetInstanceId})`} />
                      )}
                      {sp.traits?.includes("thorny") &&
                        [0, 1, 2].map((i) => (
                          <polygon
                            key={i}
                            points={`${-0.6 + i * 0.6},-3.0 ${-0.4 + i * 0.6},-3.7 ${-0.2 + i * 0.6},-3.0`}
                            fill={color}
                          />
                        ))}
                      {/* species emoji floating above */}
                      <text
                        x="0"
                        y="-3.6"
                        textAnchor="middle"
                        fontSize="2.0"
                        style={{ filter: `url(#glow-${widgetInstanceId})` }}
                      >
                        {emoji}
                      </text>
                      {/* food count */}
                      <g transform="translate(1.2, -3.1)">
                        <rect x="-0.4" y="-0.6" width={String(sp.food ?? 0).length * 0.5 + 0.6} height="0.95" rx="0.45" fill="rgba(0,0,0,0.6)" />
                        <text x="0" y="0.05" fontSize="0.85" fill="#fff7c2">{sp.food ?? 0}</text>
                      </g>
                    </g>
                  </g>
                );
              })}
          </g>
        </g>
      </svg>

      {/* ── Floating chrome — invisible until you hover the stage ──── */}
      <div className="absolute top-2 left-2 flex flex-row items-center gap-1.5 px-2 py-1 rounded-full text-[10px] tracking-wide bg-black/40 backdrop-blur-md text-white/85 border border-white/10 opacity-0 group-hover/ecosystem:opacity-100 transition-opacity duration-300 pointer-events-none">
        <span>{weatherSkin.emoji}</span>
        <span className="capitalize">{weatherSkin.label}</span>
        <span className="text-white/40">·</span>
        <span className="uppercase font-semibold tracking-wider">{phase}</span>
        <span className="text-white/40">·</span>
        <span>r{round}</span>
        {lastActor && (
          <>
            <span className="text-white/40">·</span>
            <span className="text-white/60">{lastActor === "__user__" ? "you" : (botById.get(lastActor)?.name ?? lastActor)}</span>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        className="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/30 backdrop-blur-md text-white/70 border border-white/10 flex items-center justify-center opacity-25 hover:opacity-100 group-hover/ecosystem:opacity-90 hover:bg-black/55 transition-all duration-300"
        title="Game settings"
      >
        <Settings size={12} />
      </button>

      {/* Setup hint when no participants */}
      {phase === "setup" && participants.length === 0 && (
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full text-[11px] bg-black/55 backdrop-blur-md text-white/90 border border-white/15 flex items-center gap-1.5 hover:bg-black/70 transition-colors"
        >
          <Plus size={12} />
          Add bots to begin
          <ChevronRight size={12} className="opacity-60" />
        </button>
      )}

      {/* Place-food active banner */}
      {placeFoodMode && (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[11px] bg-amber-500/30 backdrop-blur-md text-amber-100 border border-amber-200/30 flex items-center gap-2">
          Click a tile to place food
          <button onClick={() => setPlaceFoodMode(false)} className="opacity-70 hover:opacity-100">cancel</button>
        </div>
      )}

      {/* Inline error / busy chips */}
      {error && (
        <div className="absolute top-12 right-2 max-w-[60%] px-2 py-1 rounded-md text-[10px] bg-danger/30 text-danger border border-danger/40 backdrop-blur-md">
          {error}
        </div>
      )}
      {busy && !settingsOpen && (
        <div className="absolute top-12 right-2 px-2 py-1 rounded-md text-[10px] bg-black/50 backdrop-blur-md text-white/70">
          …
        </div>
      )}

      {/* ── Settings drawer (generic chrome + shared sections) ──────── */}
      <WidgetSettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        kicker="Ecosystem"
        title={phase === "setup" ? "Setup" : phase === "playing" ? `Playing · round ${round}` : "Ended"}
      >
        <GameParticipantsSection
          bots={availableBots}
          participants={participants}
          speciesByBotId={species}
          onToggle={toggleParticipant}
        />

        <GamePhaseSection
          phase={phase}
          participantCount={participants.length}
          busy={busy === "set_phase"}
          onSetPhase={(next) => void runAction("set_phase", { phase: next })}
          onAdvanceRound={() => void runAction("advance_round", {})}
        />

        {/* Weather — game-specific */}
        <WidgetSettingsSection label="Weather">
          <div className="grid grid-cols-2 gap-1.5">
            {(["neutral", "drought", "flood", "bloom"] as const).map((w) => {
              const skin = WEATHER_TINTS[w];
              const active = weather === w;
              return (
                <button
                  key={w}
                  type="button"
                  onClick={() => setWeather(w)}
                  className="px-2 py-1.5 rounded text-[11px] border transition-colors capitalize flex items-center gap-1.5"
                  style={{
                    background: active ? t.accentSubtle : "transparent",
                    borderColor: active ? t.accentBorder : t.surfaceBorder,
                    color: active ? t.text : t.textDim,
                  }}
                >
                  <span>{skin.emoji}</span>
                  <span>{skin.label}</span>
                </button>
              );
            })}
          </div>
        </WidgetSettingsSection>

        {/* Food — game-specific */}
        <WidgetSettingsSection
          label="Food sources"
          hint={`${foodSources.length} on map`}
        >
          <button
            type="button"
            onClick={() => {
              setPlaceFoodMode((v) => !v);
              setSettingsOpen(false);
            }}
            className="px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface text-left"
          >
            {placeFoodMode ? "Cancel placement" : "Place food on a tile…"}
          </button>
        </WidgetSettingsSection>

        <GameTurnLogSection
          log={turnLog}
          actorMeta={Object.fromEntries(
            participants.map((id) => [
              id,
              { name: botById.get(id)?.name, color: species[id]?.color },
            ]),
          )}
        />
      </WidgetSettingsDrawer>

      <style>{`
        /* Theme-aware atmosphere — light mode uses near-white halo with a
           cool tint; dark mode uses translucent deep-space gradient. The
           glitter color matches the canvas starfield so the widget reads
           as continuous with the canvas. */
        .ecosystem-stage {
          /* Light mode — almost transparent, just a hint of a halo so the
             asteroid has gravitas without putting a blue square behind it. */
          --eco-bg-inner: rgba(220, 232, 255, 0.10);
          --eco-bg-mid: rgba(200, 218, 245, 0.04);
          --eco-bg-outer: rgba(200, 218, 245, 0);
          --eco-star: #5a78c8;
        }
        :root.dark .ecosystem-stage,
        .dark .ecosystem-stage {
          /* Dark mode — much fainter so the widget's rectangular edge isn't
             visible against the canvas; just a hint of warmth around the rock. */
          --eco-bg-inner: rgba(40, 40, 80, 0.18);
          --eco-bg-mid: rgba(20, 20, 40, 0.08);
          --eco-bg-outer: rgba(10, 10, 25, 0);
          --eco-star: #dfe7ff;
        }
        @keyframes ecosystem-atm-twinkle {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 0.95; }
        }
        .ecosystem-atm-star {
          animation: ecosystem-atm-twinkle 4s ease-in-out infinite;
        }
        @keyframes ecosystem-bob {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-0.6px); }
        }
        @keyframes ecosystem-walk {
          0%, 100% { transform: translateX(0px); }
          50% { transform: translateX(0.4px); }
        }
        @keyframes ecosystem-drift {
          0% { transform: translate(0, 0) rotate(0deg); }
          100% { transform: translate(0.8px, -1.2px) rotate(0.4deg); }
        }
        @keyframes ecosystem-nebula-rotate {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes ecosystem-glint {
          0%, 100% { opacity: 0.55; }
          50% { opacity: 1; }
        }
        .ecosystem-bob {
          animation: ecosystem-drift 16s ease-in-out infinite alternate;
        }
        .ecosystem-nebula {
          animation: ecosystem-nebula-rotate 120s linear infinite;
        }
        .ecosystem-glint {
          animation: ecosystem-glint 2.5s ease-in-out infinite;
        }
        .ecosystem-weather-overlay {
          transition: fill 1s ease;
        }
        @media (prefers-reduced-motion: reduce) {
          .ecosystem-bob, .ecosystem-nebula, .ecosystem-glint,
          .ecosystem-atm-star, .ecosystem-bob-body {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  );
}
