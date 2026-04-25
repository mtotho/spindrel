import { useMemo, useState } from "react";
import { Plus, X, Sun, CloudRain, Droplets, Sparkles } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import {
  PreviewCard,
  type NativeAppRendererProps,
  useNativeEnvelopeState,
} from "./shared";

type EcosystemPhase = "setup" | "playing" | "ended";

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

// Procedurally generate an asteroid silhouette path. Stable per pinId so each
// instance has a recognizable shape.
function asteroidPath(seed: string, cx: number, cy: number, baseR: number): string {
  // Simple seeded PRNG (mulberry32).
  let state = 0;
  for (let i = 0; i < seed.length; i++) state = (state * 31 + seed.charCodeAt(i)) >>> 0;
  function rand() {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  const segments = 22;
  const points: Array<[number, number]> = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    // Vary the radius between 0.78 and 1.18 of base.
    const r = baseR * (0.78 + rand() * 0.4);
    points.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r * 0.92]);
  }
  // Smooth via cardinal-spline-ish: just use Q curves through midpoints.
  const path: string[] = [];
  for (let i = 0; i < points.length; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[(i + 1) % points.length];
    const mx = (x0 + x1) / 2;
    const my = (y0 + y1) / 2;
    if (i === 0) path.push(`M ${mx.toFixed(1)} ${my.toFixed(1)}`);
    path.push(`Q ${x1.toFixed(1)} ${y1.toFixed(1)} ${((x1 + points[(i + 2) % points.length][0]) / 2).toFixed(1)} ${((y1 + points[(i + 2) % points.length][1]) / 2).toFixed(1)}`);
  }
  path.push("Z");
  return path.join(" ");
}

function starfield(seed: string, count = 90): Array<{ x: number; y: number; r: number; o: number }> {
  let state = 0;
  for (let i = 0; i < seed.length; i++) state = (state * 33 + seed.charCodeAt(i)) >>> 0;
  function rand() {
    state |= 0;
    state = (state + 0x9e3779b9) | 0;
    let t = Math.imul(state ^ (state >>> 16), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  const stars: Array<{ x: number; y: number; r: number; o: number }> = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: rand() * 100,
      y: rand() * 100,
      r: rand() < 0.85 ? 0.5 : 1.1,
      o: 0.25 + rand() * 0.55,
    });
  }
  return stars;
}

const TRAIT_ICONS: Record<string, string> = {
  aggressive: "✦",
  fast: "»",
  slow: "◐",
  photosynthetic: "☀",
  parasitic: "✶",
  thorny: "⌇",
  burrowing: "▽",
  luminous: "✺",
};

const WEATHER_TINTS: Record<string, string> = {
  neutral: "transparent",
  drought: "rgba(220, 130, 50, 0.32)",
  flood: "rgba(80, 140, 220, 0.34)",
  bloom: "rgba(120, 200, 90, 0.30)",
};

function weatherIcon(weather: string) {
  if (weather === "drought") return <Sun size={12} />;
  if (weather === "flood") return <Droplets size={12} />;
  if (weather === "bloom") return <Sparkles size={12} />;
  return <CloudRain size={12} />;
}

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

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [placeFoodMode, setPlaceFoodMode] = useState(false);
  const [participantPickerOpen, setParticipantPickerOpen] = useState(false);

  const stars = useMemo(
    () => starfield(dashboardPinId ?? widgetInstanceId ?? "asteroid", 90),
    [dashboardPinId, widgetInstanceId],
  );
  const asteroidD = useMemo(
    () => asteroidPath(dashboardPinId ?? widgetInstanceId ?? "asteroid", 50, 50, 38),
    [dashboardPinId, widgetInstanceId],
  );

  const { data: bots } = useBots();
  const availableBots = useMemo(
    () => (bots ?? []).map((b) => ({ id: b.id, name: b.name ?? b.id })),
    [bots],
  );

  if (!widgetInstanceId) {
    return (
      <PreviewCard
        title="Ecosystem Sim"
        description="Async turn-based ecosystem on a tiny floating asteroid. Bots evolve species; you play the weather."
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

  function setWeather(weather: string) {
    void runAction("set_environment", { weather });
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

  // Build a sparse map of board cells → species owner for SVG rendering.
  const cells: Array<{ x: number; y: number; cell: CellRecord }> = [];
  for (let y = 0; y < BOARD_SIZE; y++) {
    for (let x = 0; x < BOARD_SIZE; x++) {
      const cell = board[y]?.[x];
      if (cell) cells.push({ x, y, cell });
    }
  }

  // Map board (12×12) onto asteroid bounding box centered at SVG (50, 50) radius 38.
  // Each cell projects into the SVG; clip-path keeps only the visible portion.
  const cellSize = 6.5; // svg units
  const boardOriginX = 50 - (cellSize * BOARD_SIZE) / 2;
  const boardOriginY = 50 - (cellSize * BOARD_SIZE) / 2;
  function cellCenter(x: number, y: number): [number, number] {
    return [
      boardOriginX + cellSize * (x + 0.5),
      boardOriginY + cellSize * (y + 0.5),
    ];
  }

  const phaseChipBg = phase === "playing" ? "rgba(120, 200, 130, 0.22)" : phase === "ended" ? "rgba(220, 90, 90, 0.22)" : "rgba(180, 180, 180, 0.18)";
  const weatherTint = WEATHER_TINTS[env.weather ?? "neutral"] ?? "transparent";

  return (
    <div className="group/ecosystem relative flex flex-col w-full h-full min-h-0 overflow-hidden text-text">
      {/* Participants strip */}
      <div className="flex flex-row items-center gap-2 px-3 py-2 border-b border-surface-border min-h-[40px]">
        <span className="text-[10px] uppercase tracking-wider text-text-dim">Species</span>
        <div className="flex flex-row items-center gap-1.5 flex-1 flex-wrap">
          {participants.length === 0 && (
            <span className="text-[11px] text-text-dim italic">No participants yet</span>
          )}
          {participants.map((botId) => {
            const sp = species[botId];
            const emoji = sp?.emoji ?? "🌱";
            const color = sp?.color ?? "#7aa2c8";
            const food = sp?.food ?? 0;
            return (
              <div
                key={botId}
                className="flex flex-row items-center gap-1 px-1.5 py-0.5 rounded text-[11px]"
                style={{ background: `${color}22`, border: `1px solid ${color}55` }}
                title={`${botId}: ${sp?.traits?.join(", ") || "no traits"} · food ${food}`}
              >
                <span>{emoji}</span>
                <span className="font-medium" style={{ color }}>{botId}</span>
                <span className="text-text-dim">·{food}</span>
              </div>
            );
          })}
          <button
            type="button"
            onClick={() => setParticipantPickerOpen((v) => !v)}
            className="flex flex-row items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-text-dim hover:text-text border border-surface-border hover:border-text-dim transition-colors"
            title="Add or remove participants"
          >
            <Plus size={11} />
            <span>add bot</span>
          </button>
        </div>
        <div
          className="flex flex-row items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px]"
          style={{ background: phaseChipBg, color: t.text }}
        >
          <span className="font-semibold uppercase tracking-wide">{phase}</span>
          <span className="text-text-dim">· r{round}</span>
          {lastActor && <span className="text-text-dim">· last {lastActor}</span>}
        </div>
      </div>

      {participantPickerOpen && (
        <div className="px-3 py-2 border-b border-surface-border bg-surface flex flex-row items-center gap-2 flex-wrap">
          {availableBots.length === 0 && (
            <span className="text-[11px] text-text-dim">No bots configured.</span>
          )}
          {availableBots.map((b) => {
            const active = participants.includes(b.id);
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => toggleParticipant(b.id)}
                className="px-2 py-0.5 rounded text-[11px] border transition-colors"
                style={{
                  background: active ? t.accentSubtle : "transparent",
                  borderColor: active ? t.accentBorder : t.surfaceBorder,
                  color: active ? t.text : t.textDim,
                }}
                title={active ? "Remove from game" : "Add to game"}
              >
                {b.name}
              </button>
            );
          })}
          <button
            type="button"
            className="ml-auto text-[11px] text-text-dim hover:text-text"
            onClick={() => setParticipantPickerOpen(false)}
          >
            done
          </button>
        </div>
      )}

      {/* Asteroid stage */}
      <div className="relative flex-1 min-h-0 overflow-hidden">
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle at 50% 45%, #0e1428 0%, #07091a 60%, #04050d 100%)",
          }}
        />
        {/* Subtle conic nebula (slow rotation via CSS keyframe inlined) */}
        <div
          aria-hidden
          className="absolute inset-0 mix-blend-screen opacity-40 ecosystem-nebula"
          style={{
            background:
              "conic-gradient(from 0deg, rgba(120,80,180,0.06), rgba(50,90,180,0.03), rgba(180,80,140,0.05), rgba(120,80,180,0.06))",
          }}
        />
        {/* Starfield */}
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 100 100"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden
        >
          {stars.map((s, i) => (
            <circle
              key={i}
              cx={s.x}
              cy={s.y}
              r={s.r * 0.3}
              fill="#dfe7ff"
              opacity={s.o}
              className="ecosystem-star"
              style={{ animationDelay: `${(i % 12) * 0.4}s` }}
            />
          ))}
        </svg>

        {/* Asteroid + vegetation */}
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 100 100"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <radialGradient id={`rock-${widgetInstanceId}`} cx="0.42" cy="0.38" r="0.7">
              <stop offset="0%" stopColor="#b08a6a" />
              <stop offset="45%" stopColor="#7a5a44" />
              <stop offset="100%" stopColor="#2d1f17" />
            </radialGradient>
            <filter id={`rim-${widgetInstanceId}`}>
              <feGaussianBlur stdDeviation="0.6" />
            </filter>
            <clipPath id={`asteroid-clip-${widgetInstanceId}`}>
              <path d={asteroidD} />
            </clipPath>
          </defs>
          <g className="ecosystem-drift">
            {/* Rim glow */}
            <path
              d={asteroidD}
              fill="none"
              stroke="rgba(170, 200, 255, 0.35)"
              strokeWidth="0.5"
              filter={`url(#rim-${widgetInstanceId})`}
            />
            {/* Body */}
            <path d={asteroidD} fill={`url(#rock-${widgetInstanceId})`} />
            {/* Inner shadow */}
            <path
              d={asteroidD}
              fill="none"
              stroke="rgba(0, 0, 0, 0.45)"
              strokeWidth="2"
              clipPath={`url(#asteroid-clip-${widgetInstanceId})`}
            />
            {/* Weather overlay */}
            {weatherTint !== "transparent" && (
              <path d={asteroidD} fill={weatherTint} />
            )}

            {/* Cells */}
            <g clipPath={`url(#asteroid-clip-${widgetInstanceId})`}>
              {cells.map(({ x, y, cell }) => {
                const owner = cell.owner;
                const sp = species[owner];
                const color = sp?.color ?? "#7aa2c8";
                const traits = sp?.traits ?? [];
                const [cx, cy] = cellCenter(x, y);
                return (
                  <g key={`${x}-${y}`} transform={`translate(${cx} ${cy})`}>
                    {/* Vegetation patch */}
                    <circle r={cellSize * 0.42} fill={color} opacity={0.85} />
                    <circle r={cellSize * 0.22} fill="#fff" opacity={0.15} />
                    {/* Trait flourishes */}
                    {traits.includes("aggressive") &&
                      [0, 1, 2, 3, 4, 5].map((i) => {
                        const a = (i / 6) * Math.PI * 2;
                        const r1 = cellSize * 0.42;
                        const r2 = cellSize * 0.62;
                        return (
                          <line
                            key={i}
                            x1={Math.cos(a) * r1}
                            y1={Math.sin(a) * r1}
                            x2={Math.cos(a) * r2}
                            y2={Math.sin(a) * r2}
                            stroke={color}
                            strokeWidth={0.4}
                            opacity={0.85}
                          />
                        );
                      })}
                    {traits.includes("photosynthetic") && (
                      <circle r={cellSize * 0.55} fill="none" stroke="#fff7c2" strokeWidth={0.25} opacity={0.55} />
                    )}
                    {traits.includes("luminous") && (
                      <circle r={cellSize * 0.18} fill="#fff7e0" opacity={0.85} />
                    )}
                    {traits.includes("thorny") &&
                      [0, 1, 2, 3].map((i) => {
                        const a = (i / 4) * Math.PI * 2 + 0.4;
                        return (
                          <polygon
                            key={i}
                            points={`0,0 ${(Math.cos(a) * cellSize * 0.55).toFixed(2)},${(Math.sin(a) * cellSize * 0.55).toFixed(2)} ${(Math.cos(a + 0.25) * cellSize * 0.35).toFixed(2)},${(Math.sin(a + 0.25) * cellSize * 0.35).toFixed(2)}`}
                            fill={color}
                            opacity={0.7}
                          />
                        );
                      })}
                    {traits.includes("fast") &&
                      [0, 1, 2].map((i) => (
                        <line
                          key={i}
                          x1={cellSize * 0.5}
                          y1={(i - 1) * cellSize * 0.18}
                          x2={cellSize * 0.85}
                          y2={(i - 1) * cellSize * 0.18}
                          stroke={color}
                          strokeWidth={0.25}
                          opacity={0.55}
                        />
                      ))}
                  </g>
                );
              })}

              {/* Food source glints */}
              {foodSources.map((src, i) => {
                const [cx, cy] = cellCenter(src.x, src.y);
                return (
                  <g key={`food-${i}`} transform={`translate(${cx} ${cy})`} className="ecosystem-glint">
                    <circle r={1.6} fill="#fff7c2" opacity={0.75} />
                    <circle r={0.8} fill="#ffeb88" />
                  </g>
                );
              })}

              {/* Place-food click capture */}
              {placeFoodMode &&
                Array.from({ length: BOARD_SIZE }, (_, y) =>
                  Array.from({ length: BOARD_SIZE }, (_, x) => {
                    const [cx, cy] = cellCenter(x, y);
                    const has = foodSources.find((s) => s.x === x && s.y === y);
                    return (
                      <rect
                        key={`hit-${x}-${y}`}
                        x={cx - cellSize / 2}
                        y={cy - cellSize / 2}
                        width={cellSize}
                        height={cellSize}
                        fill="rgba(255, 247, 194, 0.05)"
                        stroke="rgba(255, 247, 194, 0.25)"
                        strokeWidth={0.15}
                        style={{ cursor: "pointer" }}
                        onClick={() => (has ? clearFoodAt(x, y) : placeFoodAt(x, y))}
                      />
                    );
                  }),
                )}
            </g>
          </g>
        </svg>

        {/* Round + last_actor chip */}
        <div className="absolute top-2 left-2 px-2 py-1 rounded-md text-[10px] tracking-wide flex flex-row items-center gap-1.5 bg-surface-raised/40 backdrop-blur-sm text-text">
          {weatherIcon(env.weather ?? "neutral")}
          <span className="capitalize">{env.weather ?? "neutral"}</span>
        </div>

        {/* Turn log button */}
        <button
          type="button"
          onClick={() => setShowLog((v) => !v)}
          className="absolute bottom-2 left-2 px-2 py-1 rounded-md text-[10px] bg-surface-raised/40 backdrop-blur-sm text-text-dim hover:text-text"
        >
          {showLog ? "hide log" : `log (${turnLog.length})`}
        </button>

        {/* Turn log drawer */}
        {showLog && (
          <div className="absolute left-2 right-2 bottom-10 max-h-[55%] overflow-y-auto rounded-md bg-surface-raised/85 backdrop-blur-sm border border-surface-border p-2 text-[11px] text-text">
            {turnLog.length === 0 && (
              <div className="text-text-dim italic">No turns yet.</div>
            )}
            {[...turnLog].reverse().slice(0, 30).map((entry, i) => {
              const sp = species[entry.actor];
              const color = sp?.color ?? t.textDim;
              return (
                <div key={i} className="flex flex-row items-baseline gap-1.5 leading-snug py-0.5">
                  <span className="font-mono text-[10px]" style={{ color }}>
                    {entry.actor === "__user__" ? "you" : entry.actor}
                  </span>
                  <span className="text-text">{entry.summary || entry.action}</span>
                  {entry.reasoning && (
                    <span className="text-text-dim italic">— {entry.reasoning}</span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {error && (
          <div className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] bg-danger/20 text-danger border border-danger/40">
            {error}
          </div>
        )}
        {busy && (
          <div className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] bg-surface-raised/40 backdrop-blur-sm text-text-dim">
            …
          </div>
        )}
      </div>

      {/* User control footer */}
      <div className="flex flex-row items-center gap-2 px-3 py-2 border-t border-surface-border bg-surface flex-wrap min-h-[40px]">
        <span className="text-[10px] uppercase tracking-wider text-text-dim">Weather</span>
        {(["neutral", "drought", "flood", "bloom"] as const).map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => setWeather(w)}
            className="px-2 py-0.5 rounded text-[11px] border transition-colors capitalize"
            style={{
              background: env.weather === w ? t.accentSubtle : "transparent",
              borderColor: env.weather === w ? t.accentBorder : t.surfaceBorder,
              color: env.weather === w ? t.text : t.textDim,
            }}
          >
            {w}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setPlaceFoodMode((v) => !v)}
          className="px-2 py-0.5 rounded text-[11px] border transition-colors"
          style={{
            background: placeFoodMode ? "rgba(255, 247, 194, 0.18)" : "transparent",
            borderColor: placeFoodMode ? "rgba(255, 247, 194, 0.55)" : t.surfaceBorder,
            color: placeFoodMode ? "#fff7c2" : t.textDim,
          }}
          title={placeFoodMode ? "Click any cell to place / clear food" : "Place food source"}
        >
          {placeFoodMode ? "click cell to place / cancel" : "place food"}
        </button>

        <div className="flex-1" />

        {phase === "setup" && participants.length > 0 && (
          <button
            type="button"
            onClick={() => void runAction("set_phase", { phase: "playing" })}
            className="px-2 py-0.5 rounded text-[11px] font-medium border border-accent text-accent hover:bg-accent hover:text-white transition-colors"
          >
            start
          </button>
        )}
        {phase === "playing" && (
          <>
            <button
              type="button"
              onClick={() => void runAction("advance_round", {})}
              className="px-2 py-0.5 rounded text-[11px] border border-surface-border text-text hover:bg-surface-raised"
            >
              advance round
            </button>
            <button
              type="button"
              onClick={() => void runAction("set_phase", { phase: "ended" })}
              className="px-2 py-0.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text"
              title="End game (no more bot moves)"
            >
              <X size={12} />
            </button>
          </>
        )}
        {phase === "ended" && (
          <button
            type="button"
            onClick={() => void runAction("set_phase", { phase: "playing" })}
            className="px-2 py-0.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text"
          >
            resume
          </button>
        )}
      </div>

      <style>{`
        @keyframes ecosystem-drift {
          0% { transform: translate(0, 0) rotate(0deg); }
          100% { transform: translate(0.6px, -1px) rotate(0.5deg); }
        }
        @keyframes ecosystem-twinkle {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 0.95; }
        }
        @keyframes ecosystem-nebula-rotate {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes ecosystem-glint {
          0%, 100% { transform-origin: center; opacity: 0.55; }
          50% { opacity: 1; }
        }
        .ecosystem-drift {
          animation: ecosystem-drift 14s ease-in-out infinite alternate;
          transform-origin: 50% 50%;
        }
        .ecosystem-star {
          animation: ecosystem-twinkle 4s ease-in-out infinite;
        }
        .ecosystem-nebula {
          animation: ecosystem-nebula-rotate 80s linear infinite;
        }
        .ecosystem-glint {
          animation: ecosystem-glint 2.5s ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .ecosystem-drift, .ecosystem-star, .ecosystem-nebula, .ecosystem-glint {
            animation: none;
          }
        }
      `}</style>
    </div>
  );
}
