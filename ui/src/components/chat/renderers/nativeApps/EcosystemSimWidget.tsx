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

// Asteroid silhouette: smooth-but-irregular bottom edge below the iso
// plane. Bezier-smoothed control points with seeded perturbations read as
// weathered rock, not zigzag teeth. Top edge stays straight along the iso
// diamond so the playable surface reads cleanly.
function asteroidPath(seed: string): string {
  const rand = makeRng(seed);
  const [tx, ty] = iso(0, 0);
  const [rx, ry] = iso(BOARD_SIZE - 1, 0);
  const [bx, by] = iso(BOARD_SIZE - 1, BOARD_SIZE - 1);
  const [lx, ly] = iso(0, BOARD_SIZE - 1);

  // Walk perimeter right→bottom→left through perturbed waypoints.
  const segments = 11;
  const pts: Array<[number, number]> = [];
  for (let i = 1; i <= segments; i++) {
    const t = i / (segments + 1);
    // Lerp from right corner down toward the bottom apex with extra hang.
    const baseX = rx + (bx - rx) * t;
    const baseY = ry + (by - ry) * t;
    // Hang depth peaks near the middle.
    const hang = ISO_DEPTH * (0.6 + 1.0 * Math.sin(t * Math.PI));
    const jx = (rand() - 0.5) * ISO_TILE_W * 1.0;
    const jy = (rand() - 0.5) * ISO_DEPTH * 0.35;
    pts.push([baseX + jx, baseY + hang + jy]);
  }
  // Bottom-most beak point (most pronounced hang).
  pts.push([bx + (rand() - 0.5) * ISO_TILE_W, by + ISO_DEPTH * (1.6 + rand() * 0.4)]);
  for (let i = 1; i <= segments; i++) {
    const t = i / (segments + 1);
    const baseX = bx + (lx - bx) * t;
    const baseY = by + (ly - by) * t;
    const hang = ISO_DEPTH * (0.6 + 1.0 * Math.sin((1 - t) * Math.PI));
    const jx = (rand() - 0.5) * ISO_TILE_W * 1.0;
    const jy = (rand() - 0.5) * ISO_DEPTH * 0.35;
    pts.push([baseX + jx, baseY + hang + jy]);
  }

  // Build path: straight line along the top iso diamond, smooth Q-curves
  // through the underside. Each control point is the waypoint; the curve
  // ends at the midpoint between neighbours so the rock reads continuous.
  const path: string[] = [];
  path.push(`M ${tx.toFixed(1)} ${ty.toFixed(1)}`);
  path.push(`L ${rx.toFixed(1)} ${ry.toFixed(1)}`);
  // First segment: from rx,ry curve toward midpoint of (rx,ry)↔pts[0].
  const first = pts[0];
  const firstMid: [number, number] = [(rx + first[0]) / 2, (ry + first[1]) / 2];
  path.push(`L ${firstMid[0].toFixed(1)} ${firstMid[1].toFixed(1)}`);
  for (let i = 0; i < pts.length; i++) {
    const cur = pts[i];
    const next = pts[i + 1];
    if (next) {
      const mx = (cur[0] + next[0]) / 2;
      const my = (cur[1] + next[1]) / 2;
      path.push(
        `Q ${cur[0].toFixed(1)} ${cur[1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`,
      );
    } else {
      // Curve to (lx,ly) with cur as control point.
      path.push(
        `Q ${cur[0].toFixed(1)} ${cur[1].toFixed(1)} ${lx.toFixed(1)} ${ly.toFixed(1)}`,
      );
    }
  }
  path.push("Z");
  return path.join(" ");
}

// Procedural craters on the top surface — small darker ovals with a
// brighter rim on the upper-left to suggest shadow casting from a star to
// the upper-left. Seeded so each asteroid looks distinct.
interface Crater { cx: number; cy: number; rx: number; ry: number; }
function craters(seed: string, count = 4): Crater[] {
  const rand = makeRng(`${seed}-craters`);
  const out: Crater[] = [];
  for (let i = 0; i < count; i++) {
    // Pick a board cell roughly in the inner 80% of the diamond.
    const gx = 1 + rand() * (BOARD_SIZE - 3);
    const gy = 1 + rand() * (BOARD_SIZE - 3);
    const [sx, sy] = iso(gx, gy);
    const r = 1.4 + rand() * 1.2;
    out.push({ cx: sx, cy: sy, rx: r, ry: r * 0.55 });
  }
  return out;
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
  const surfaceCraters = useMemo(() => craters(seed, 4), [seed]);
  // Weather particles — drought dust motes, flood ripple drops, bloom petals.
  // Each gets a deterministic seed so the canvas isn't reshuffled every render.
  const weatherParticles = useMemo(() => {
    const rand = makeRng(`${seed}-weather-${weather}`);
    const out: Array<{ x: number; y: number; r: number; phase: number; drift: number }> = [];
    if (weather === "neutral") return out;
    const count = weather === "bloom" ? 18 : weather === "drought" ? 22 : 14;
    for (let i = 0; i < count; i++) {
      out.push({
        x: 30 + rand() * 140,
        y: 30 + rand() * 70,
        r: 0.35 + rand() * 0.55,
        phase: rand() * 6,
        drift: -1 + rand() * 2,
      });
    }
    return out;
  }, [seed, weather]);
  // Surface specks — pre-compute once per seed so they don't re-shuffle on
  // every render. Pulled out of a `useMemo` inside `.map()` (anti-pattern).
  const surfaceSpecks = useMemo(() => {
    const rand = makeRng(`${seed}-specks`);
    const dots: Array<{ cx: number; cy: number; r: number; o: number; tone: string }> = [];
    for (let i = 0; i < 90; i++) {
      const gx = rand() * (BOARD_SIZE - 1);
      const gy = rand() * (BOARD_SIZE - 1);
      const [sx, sy] = iso(gx, gy);
      const isDark = rand() < 0.35;
      dots.push({
        cx: sx,
        cy: sy,
        r: 0.14 + rand() * 0.24,
        o: 0.18 + rand() * 0.22,
        tone: isDark ? "#2a1810" : "#f0d3a8",
      });
    }
    return dots;
  }, [seed]);

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

        {/* Asteroid body — bobs gently. No ground shadow: it's drifting in
            open space, there's nothing for a shadow to fall on. */}
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

          {/* Surface texture: scattered rock specks (warm + dark mix) */}
          <g clipPath={`url(#top-clip-${widgetInstanceId})`}>
            {surfaceSpecks.map((d, i) => (
              <circle key={i} cx={d.cx} cy={d.cy} r={d.r} fill={d.tone} opacity={d.o} />
            ))}
          </g>

          {/* Craters — soft elliptical dimples with a bright upper rim
              (implied star upper-left) and a dark inner basin. Adds depth
              without making the surface noisy. */}
          <g clipPath={`url(#top-clip-${widgetInstanceId})`}>
            {surfaceCraters.map((c, i) => (
              <g key={`crater-${i}`}>
                {/* basin */}
                <ellipse cx={c.cx} cy={c.cy} rx={c.rx} ry={c.ry} fill="#1d130c" opacity={0.45} />
                {/* inner highlight */}
                <ellipse
                  cx={c.cx - c.rx * 0.25}
                  cy={c.cy - c.ry * 0.35}
                  rx={c.rx * 0.55}
                  ry={c.ry * 0.4}
                  fill="#c79a73"
                  opacity={0.3}
                />
                {/* rim catchlight */}
                <ellipse
                  cx={c.cx}
                  cy={c.cy}
                  rx={c.rx}
                  ry={c.ry}
                  fill="none"
                  stroke="#f4d8b4"
                  strokeWidth={0.18}
                  opacity={0.35}
                />
              </g>
            ))}
          </g>

          {/* Directional rim light — implied star to the upper-left casts a
              warm crescent on the top surface. Positioned via clip so it
              only paints the top diamond. */}
          <g clipPath={`url(#top-clip-${widgetInstanceId})`} opacity={0.18}>
            <ellipse cx={70} cy={32} rx={42} ry={14} fill="#fff5d8" />
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
                const stalkLen = traits.includes("slow")
                  ? -2.8
                  : traits.includes("fast")
                  ? -1.7
                  : -2.1;
                const bulbR = traits.includes("slow") ? 1.05 : 0.9;
                const burrowed = traits.includes("burrowing");
                return (
                  <g key={`v-${x}-${y}`} transform={`translate(${sx} ${sy})`}>
                    <title>{`Cell (${x},${y}) · ${owner}${
                      cell.food ? ` · ${cell.food} food` : ""
                    }${traits.length ? ` · ${traits.join(", ")}` : ""}`}</title>
                    {/* Soft ground halo */}
                    <ellipse cx="0" cy="0.5" rx="2.2" ry="1.0" fill={color} opacity={burrowed ? 0.45 : 0.22} />
                    {/* Burrowing — only the top of the bulb pokes through; small mound below */}
                    {burrowed && (
                      <ellipse cx="0" cy="0.25" rx="1.5" ry="0.55" fill="#3a2818" opacity={0.55} />
                    )}
                    {/* Stalk (skipped if burrowing) */}
                    {!burrowed && (
                      <line
                        x1="0"
                        y1="0"
                        x2="0"
                        y2={stalkLen}
                        stroke={color}
                        strokeWidth={traits.includes("slow") ? 0.6 : 0.4}
                      />
                    )}
                    {/* Photosynthetic — leaf-pair on the stalk */}
                    {traits.includes("photosynthetic") && !burrowed && (
                      <>
                        <ellipse
                          cx={-0.7}
                          cy={stalkLen * 0.5}
                          rx={0.7}
                          ry={0.3}
                          fill="#7cc77a"
                          transform={`rotate(-25 ${-0.7} ${stalkLen * 0.5})`}
                        />
                        <ellipse
                          cx={0.7}
                          cy={stalkLen * 0.5 + 0.2}
                          rx={0.7}
                          ry={0.3}
                          fill="#7cc77a"
                          transform={`rotate(25 ${0.7} ${stalkLen * 0.5 + 0.2})`}
                        />
                      </>
                    )}
                    {/* Bulb (smaller if burrowing) */}
                    <circle
                      cx="0"
                      cy={burrowed ? -0.3 : stalkLen}
                      r={burrowed ? 0.6 : bulbR}
                      fill={color}
                    />
                    {/* Photosynthetic glow ring */}
                    {traits.includes("photosynthetic") && (
                      <circle cx="0" cy={burrowed ? -0.3 : stalkLen} r={1.6} fill="none" stroke="#fff7c2" strokeWidth={0.18} opacity={0.55} />
                    )}
                    {/* Luminous — bright pip */}
                    {traits.includes("luminous") && (
                      <circle cx="0" cy={burrowed ? -0.3 : stalkLen} r={0.4} fill="#fff7e0" opacity={0.95} />
                    )}
                    {/* Thorny — spikes radiating from bulb */}
                    {traits.includes("thorny") && !burrowed &&
                      [0, 1, 2, 3, 4].map((i) => {
                        const a = (i / 5) * Math.PI * 2;
                        return (
                          <line
                            key={i}
                            x1={Math.cos(a) * 0.9}
                            y1={stalkLen + Math.sin(a) * 0.9}
                            x2={Math.cos(a) * 1.5}
                            y2={stalkLen + Math.sin(a) * 1.5}
                            stroke={color}
                            strokeWidth={0.18}
                            opacity={0.85}
                          />
                        );
                      })}
                    {/* Aggressive — small fang triangle on bulb */}
                    {traits.includes("aggressive") && !burrowed && (
                      <polygon
                        points={`-0.5,${stalkLen + 0.7} 0,${stalkLen - 0.4} 0.5,${stalkLen + 0.7}`}
                        fill="#fff"
                        opacity={0.7}
                      />
                    )}
                    {/* Fast — speed lines trailing right of stalk */}
                    {traits.includes("fast") && !burrowed &&
                      [0, 1].map((i) => (
                        <line
                          key={i}
                          x1={1.0}
                          y1={stalkLen + 0.4 + i * 0.4}
                          x2={2.2}
                          y2={stalkLen + 0.4 + i * 0.4}
                          stroke={color}
                          strokeWidth={0.15}
                          opacity={0.55}
                        />
                      ))}
                    {/* Parasitic — wavy tendril reaching out */}
                    {traits.includes("parasitic") && !burrowed && (
                      <path
                        d={`M 0 ${stalkLen} Q 1.4 ${stalkLen - 0.3} 1.8 ${stalkLen + 0.6} T 2.6 ${stalkLen + 0.4}`}
                        stroke={color}
                        strokeWidth={0.2}
                        fill="none"
                        opacity={0.75}
                      />
                    )}
                  </g>
                );
              })}
          </g>

          {/* Weather particles — drifting visual life. Each system has its
              own form: drought = dust motes rising, flood = falling drops,
              bloom = floating petals. Position is per-particle, animation is
              CSS-driven for cheapness. */}
          {weather !== "neutral" && (
            <g className="ecosystem-weather-particles" opacity={0.85}>
              {weatherParticles.map((p, i) => {
                const delay = `${p.phase}s`;
                if (weather === "drought") {
                  return (
                    <circle
                      key={`wp-${i}`}
                      cx={p.x}
                      cy={p.y}
                      r={p.r * 0.8}
                      fill="#dcae7c"
                      opacity={0.65}
                      className="ecosystem-dust"
                      style={{ animationDelay: delay }}
                    />
                  );
                }
                if (weather === "flood") {
                  return (
                    <line
                      key={`wp-${i}`}
                      x1={p.x}
                      y1={p.y}
                      x2={p.x + p.drift * 0.4}
                      y2={p.y + 1.6}
                      stroke="#9ec9f5"
                      strokeWidth={0.22}
                      strokeLinecap="round"
                      opacity={0.7}
                      className="ecosystem-drop"
                      style={{ animationDelay: delay }}
                    />
                  );
                }
                // bloom — simple petal as a tiny rotated ellipse
                return (
                  <ellipse
                    key={`wp-${i}`}
                    cx={p.x}
                    cy={p.y}
                    rx={p.r * 0.9}
                    ry={p.r * 0.45}
                    fill="#f7c0d8"
                    opacity={0.75}
                    transform={`rotate(${p.drift * 30} ${p.x} ${p.y})`}
                    className="ecosystem-petal"
                    style={{ animationDelay: delay }}
                  />
                );
              })}
            </g>
          )}

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

          {/* Bot characters — bobbing, rendered last so they sit on top.
              Trait visuals: aggressive=fang mouth, luminous=glow pip,
              thorny=head spikes, photosynthetic=leaf antenna, parasitic=
              tendril, fast=lean+streaks, slow=larger body, burrowing=
              half-buried. */}
          <g>
            {botAvatars
              .sort((a, b) => a.sy - b.sy)
              .map(({ botId, sx, sy, species: sp, phase: phaseOffset }) => {
                const color = sp.color || "#7aa2c8";
                const emoji = sp.emoji || "🌱";
                const tr = sp.traits ?? [];
                const fast = tr.includes("fast");
                const slow = tr.includes("slow");
                const burrowing = tr.includes("burrowing");
                const bodyScale = slow ? 1.18 : fast ? 0.92 : 1.0;
                const buriedY = burrowing ? 0.9 : 0;
                return (
                  // Position-only outer group. SVG attribute transform —
                  // never wear a CSS animation here, or the animation's
                  // `transform` will override this and snap the bot to (0,0).
                  <g
                    key={`bot-${botId}`}
                    transform={`translate(${sx} ${sy + buriedY})`}
                  >
                    <title>
                      {`${botId}${tr.length ? ` · ${tr.join(", ")}` : ""} · ${sp.food ?? 0} food`}
                    </title>
                    {/* Walk animation — runs on a child group so the CSS
                        `transform` keyframes don't fight the SVG positional
                        transform on the outer wrapper. */}
                    <g
                      style={{
                        animation: `ecosystem-walk ${slow ? 8 : fast ? 3.5 : 5.5}s ease-in-out infinite`,
                        animationDelay: `${phaseOffset * -5.5}s`,
                      }}
                    >
                    {/* contact shadow */}
                    <ellipse cx="0" cy="0.4" rx={1.6 * bodyScale} ry="0.5" fill={`url(#bot-shadow-${widgetInstanceId})`} />
                    {/* burrowing — small dirt mound around the base */}
                    {burrowing && (
                      <ellipse cx="0" cy="0.1" rx={1.7} ry="0.55" fill="#2a1810" opacity={0.7} />
                    )}
                    {/* bobbing body */}
                    <g
                      className="ecosystem-bob-body"
                      style={{
                        animation: `ecosystem-bob ${slow ? 3.4 : fast ? 1.2 : 2.2}s ease-in-out infinite`,
                        animationDelay: `${phaseOffset * -2.2}s`,
                        transform: fast ? "rotate(-4deg)" : undefined,
                        transformOrigin: "0px 0px",
                      }}
                    >
                      {/* back foot/stalk (suppressed when burrowing) */}
                      {!burrowing && (
                        <>
                          <ellipse cx="-0.55" cy="0" rx="0.35" ry="0.25" fill={color} opacity={0.85} />
                          <ellipse cx="0.55" cy="0" rx="0.35" ry="0.25" fill={color} opacity={0.85} />
                        </>
                      )}
                      {/* body */}
                      <ellipse cx="0" cy="-1.4" rx={1.55 * bodyScale} ry={1.85 * bodyScale} fill={color} />
                      {/* belly highlight */}
                      <ellipse cx={-0.3 * bodyScale} cy={-1.7} rx={0.6 * bodyScale} ry={0.85 * bodyScale} fill="#fff" opacity={0.25} />
                      {/* eyes */}
                      <circle cx="-0.5" cy="-1.5" r="0.32" fill="#fff" />
                      <circle cx="0.55" cy="-1.5" r="0.32" fill="#fff" />
                      <circle cx="-0.4" cy="-1.45" r="0.16" fill="#0b0612" />
                      <circle cx="0.65" cy="-1.45" r="0.16" fill="#0b0612" />
                      {/* mouth — reflects "aggressive" */}
                      {tr.includes("aggressive") ? (
                        <polygon points="-0.45,-0.85 0,-0.45 0.45,-0.85" fill="#0b0612" />
                      ) : (
                        <path d="M -0.4 -0.9 Q 0 -0.65 0.4 -0.9" stroke="#0b0612" strokeWidth={0.14} fill="none" strokeLinecap="round" />
                      )}
                      {/* photosynthetic — leaf antenna */}
                      {tr.includes("photosynthetic") && (
                        <g transform="translate(0 -3.0)">
                          <line x1="0" y1="0" x2="0" y2="-0.6" stroke="#5fa658" strokeWidth={0.14} />
                          <ellipse cx={0.4} cy={-0.7} rx={0.55} ry={0.28} fill="#7cc77a" transform="rotate(-25 0.4 -0.7)" />
                          <ellipse cx={-0.4} cy={-0.55} rx={0.45} ry={0.22} fill="#7cc77a" transform="rotate(25 -0.4 -0.55)" />
                        </g>
                      )}
                      {/* luminous — glowing pip on forehead */}
                      {tr.includes("luminous") && (
                        <circle cx="0" cy="-3.1" r="0.3" fill="#fff7e0" opacity="0.9" filter={`url(#glow-${widgetInstanceId})`} />
                      )}
                      {/* thorny — head spikes */}
                      {tr.includes("thorny") &&
                        [0, 1, 2].map((i) => (
                          <polygon
                            key={i}
                            points={`${-0.6 + i * 0.6},-3.0 ${-0.4 + i * 0.6},-3.7 ${-0.2 + i * 0.6},-3.0`}
                            fill={color}
                          />
                        ))}
                      {/* parasitic — tendril reaching off the body */}
                      {tr.includes("parasitic") && (
                        <path
                          d={`M ${1.3 * bodyScale} -1.6 Q ${2.0 * bodyScale} -2.0 ${1.6 * bodyScale} -2.6 T ${2.4 * bodyScale} -3.0`}
                          stroke={color}
                          strokeWidth={0.18}
                          fill="none"
                          opacity={0.85}
                        />
                      )}
                      {/* fast — speed streaks behind body */}
                      {fast &&
                        [0, 1, 2].map((i) => (
                          <line
                            key={`fs-${i}`}
                            x1={1.6 * bodyScale}
                            y1={-1.4 + (i - 1) * 0.4}
                            x2={2.6 * bodyScale}
                            y2={-1.4 + (i - 1) * 0.4}
                            stroke={color}
                            strokeWidth={0.13}
                            opacity={0.6}
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
                      <g transform={`translate(${1.2 * bodyScale}, -3.1)`}>
                        <rect x="-0.4" y="-0.6" width={String(sp.food ?? 0).length * 0.5 + 0.6} height="0.95" rx="0.45" fill="rgba(0,0,0,0.6)" />
                        <text x="0" y="0.05" fontSize="0.85" fill="#fff7c2">{sp.food ?? 0}</text>
                      </g>
                    </g>
                    </g>
                  </g>
                );
              })}
          </g>
        </g>
      </svg>

      {/* ── Floating chrome — always faintly visible, brightens on hover ──
          Lets the player glance at round/phase/weather without committing
          to opening settings. */}
      <div className="absolute top-2 left-2 flex flex-row items-center gap-1.5 px-2 py-1 rounded-full text-[10px] tracking-wide bg-black/35 backdrop-blur-md text-white/85 border border-white/10 opacity-25 group-hover/ecosystem:opacity-100 transition-opacity duration-300 pointer-events-none">
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

        {/* Feed — direct food balance lever, only useful once playing */}
        {phase === "playing" && participants.length > 0 && (
          <WidgetSettingsSection
            label="Feed species"
            hint="Hand out or take food directly"
          >
            <div className="flex flex-col gap-1">
              {participants.map((id) => {
                const sp = species[id];
                if (!sp) return null;
                const name = botById.get(id)?.name ?? id;
                return (
                  <div
                    key={id}
                    className="flex items-center gap-2 px-2 py-1 rounded border border-surface-border bg-surface"
                  >
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ background: sp.color }}
                    />
                    <span className="text-[12px] flex-1 truncate">{name}</span>
                    <span className="text-[11px] text-text-dim font-mono w-7 text-right">
                      {sp.food ?? 0}
                    </span>
                    <button
                      type="button"
                      onClick={() => void runAction("feed_species", { bot_id: id, amount: -1 }, `feed-${id}`)}
                      className="w-6 h-6 rounded text-[12px] border border-surface-border hover:bg-surface-raised text-text-dim disabled:opacity-40"
                      disabled={busy === `feed-${id}` || (sp.food ?? 0) <= 0}
                      title="Take 1 food"
                    >
                      −
                    </button>
                    <button
                      type="button"
                      onClick={() => void runAction("feed_species", { bot_id: id, amount: 1 }, `feed-${id}`)}
                      className="w-6 h-6 rounded text-[12px] border border-surface-border hover:bg-surface-raised text-text disabled:opacity-40"
                      disabled={busy === `feed-${id}`}
                      title="Give 1 food"
                    >
                      +
                    </button>
                  </div>
                );
              })}
            </div>
          </WidgetSettingsSection>
        )}

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
        /* Drought — dust motes drift up and fade. */
        @keyframes ecosystem-dust {
          0%   { transform: translate(0, 0); opacity: 0; }
          15%  { opacity: 0.75; }
          80%  { opacity: 0.55; }
          100% { transform: translate(2px, -8px); opacity: 0; }
        }
        .ecosystem-dust {
          animation: ecosystem-dust 6s ease-in-out infinite;
        }
        /* Flood — drops fall and fade. */
        @keyframes ecosystem-drop {
          0%   { transform: translate(0, -3px); opacity: 0; }
          25%  { opacity: 0.95; }
          100% { transform: translate(0, 8px); opacity: 0; }
        }
        .ecosystem-drop {
          animation: ecosystem-drop 2.4s linear infinite;
        }
        /* Bloom — petals float side to side. */
        @keyframes ecosystem-petal {
          0%   { transform: translate(0, 0) rotate(0deg); opacity: 0; }
          15%  { opacity: 0.85; }
          100% { transform: translate(3px, -6px) rotate(180deg); opacity: 0; }
        }
        .ecosystem-petal {
          animation: ecosystem-petal 7s ease-in-out infinite;
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
          .ecosystem-atm-star, .ecosystem-bob-body,
          .ecosystem-dust, .ecosystem-drop, .ecosystem-petal {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  );
}
