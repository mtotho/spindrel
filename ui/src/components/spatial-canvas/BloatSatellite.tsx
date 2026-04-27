import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Wind, X } from "lucide-react";
import { useAgentSmell, type AgentSmellBot } from "../../api/hooks/useUsage";

const SATELLITE_OFFSET_X = 110;
const SATELLITE_OFFSET_Y = -60;

const DRAWER_WIDTH = 480;
const DRAWER_HEIGHT = 560;
const DRAWER_GAP = 16;

function fmtTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
}

function severityClass(severity: string): string {
  if (severity === "critical") return "border-danger/65 bg-danger/15 text-danger";
  if (severity === "smelly") return "border-warning/70 bg-warning/15 text-warning";
  if (severity === "watch") return "border-accent/55 bg-accent/15 text-accent";
  return "border-success/60 bg-success/15 text-success";
}

interface BloatSatelliteProps {
  /** Live world position of the Attention Hub landmark; the satellite
   *  anchors its small orbit relative to the hub so dragging the hub
   *  carries the bloat callout with it. */
  hubX: number;
  hubY: number;
}

export function BloatSatellite({ hubX, hubY }: BloatSatelliteProps) {
  const [drawerAnchor, setDrawerAnchor] = useState<{ x: number; y: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const { data } = useAgentSmell({ hours: 24, baseline_days: 7, limit: 25 });
  const summary = data?.summary;
  const bloatedBotCount = summary?.bloated_bot_count ?? 0;
  if (!data || bloatedBotCount === 0) return null;

  const offenders = data.bots.filter((b) =>
    b.reasons.some((r) => r.key === "context_bloat"),
  );

  const handleOpen = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) {
      setDrawerAnchor({ x: 80, y: 80 });
      return;
    }
    // Place the drawer to the right of the satellite by default, then
    // clamp inside the viewport so it stays fully visible. Falls back to
    // the left side if there isn't room on the right.
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let x = rect.right + DRAWER_GAP;
    if (x + DRAWER_WIDTH + DRAWER_GAP > vw) {
      x = Math.max(DRAWER_GAP, rect.left - DRAWER_WIDTH - DRAWER_GAP);
    }
    let y = rect.top;
    if (y + DRAWER_HEIGHT + DRAWER_GAP > vh) {
      y = Math.max(DRAWER_GAP, vh - DRAWER_HEIGHT - DRAWER_GAP);
    }
    setDrawerAnchor({ x, y });
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`absolute flex flex-col items-center justify-center rounded-full border-2 shadow-md backdrop-blur transition-transform hover:scale-110 ${severityClass(summary?.max_severity ?? "watch")}`}
        style={{
          left: hubX + SATELLITE_OFFSET_X - 32,
          top: hubY + SATELLITE_OFFSET_Y - 32,
          width: 64,
          height: 64,
          zIndex: 5,
        }}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={handleOpen}
        title={`Context bloat: ${bloatedBotCount} bot${bloatedBotCount === 1 ? "" : "s"} carrying unused tools/skills`}
      >
        <Wind size={22} />
        <span className="mt-0.5 text-[11px] font-semibold leading-none">{bloatedBotCount}</span>
      </button>
      {drawerAnchor ? (
        <BloatDrawer
          offenders={offenders}
          summary={summary}
          initialX={drawerAnchor.x}
          initialY={drawerAnchor.y}
          onClose={() => setDrawerAnchor(null)}
        />
      ) : null}
    </>
  );
}

function BloatDrawer({
  offenders,
  summary,
  initialX,
  initialY,
  onClose,
}: {
  offenders: AgentSmellBot[];
  summary: { total_unused_tools: number; total_pinned_unused_tools: number; total_unused_skills: number; total_estimated_bloat_tokens: number } | undefined;
  initialX: number;
  initialY: number;
  onClose: () => void;
}) {
  const [pos, setPos] = useState({ x: initialX, y: initialY });
  const dragRef = useRef<{ pointerId: number; offsetX: number; offsetY: number } | null>(null);

  // Re-clamp on viewport resize so the panel never gets stranded offscreen.
  useEffect(() => {
    const onResize = () => {
      setPos((p) => ({
        x: Math.min(Math.max(DRAWER_GAP, p.x), window.innerWidth - DRAWER_WIDTH - DRAWER_GAP),
        y: Math.min(Math.max(DRAWER_GAP, p.y), window.innerHeight - DRAWER_HEIGHT - DRAWER_GAP),
      }));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const onHeaderPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      dragRef.current = {
        pointerId: e.pointerId,
        offsetX: e.clientX - pos.x,
        offsetY: e.clientY - pos.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [pos.x, pos.y],
  );

  const onHeaderPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    e.preventDefault();
    const x = Math.min(
      Math.max(DRAWER_GAP, e.clientX - d.offsetX),
      window.innerWidth - DRAWER_WIDTH - DRAWER_GAP,
    );
    const y = Math.min(
      Math.max(DRAWER_GAP, e.clientY - d.offsetY),
      window.innerHeight - DRAWER_HEIGHT - DRAWER_GAP,
    );
    setPos({ x, y });
  }, []);

  const onHeaderPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    dragRef.current = null;
  }, []);

  return (
    <aside
      className="fixed z-[70] flex flex-col rounded-md bg-surface-raised/95 text-sm text-text shadow-xl ring-1 ring-surface-border backdrop-blur"
      style={{
        left: pos.x,
        top: pos.y,
        width: DRAWER_WIDTH,
        height: DRAWER_HEIGHT,
      }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div
        className="flex cursor-move items-center justify-between border-b border-surface-border px-4 py-3 select-none"
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
        onPointerCancel={onHeaderPointerUp}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.08em] text-text-dim">
            <Wind size={14} />
            Context Bloat
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {summary
              ? `${summary.total_unused_tools} unused · ${summary.total_pinned_unused_tools} pinned-unused · ~${fmtTokens(summary.total_estimated_bloat_tokens)} tokens/turn`
              : null}
          </div>
        </div>
        <button
          type="button"
          className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={onClose}
          title="Close"
        >
          <X size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3 space-y-3">
        {offenders.length === 0 ? (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-4 text-xs text-text-dim">
            No bloated working sets right now.
          </div>
        ) : (
          offenders.map((bot) => <BloatRow key={bot.bot_id} bot={bot} />)
        )}
      </div>
    </aside>
  );
}

function BloatRow({ bot }: { bot: AgentSmellBot }) {
  const name = bot.display_name || bot.name || bot.bot_id;
  const m = bot.metrics;
  const enrolledTools = m.enrolled_tools_count ?? 0;
  const unusedTools = m.unused_tools_count ?? 0;
  const enrolledSkills = m.enrolled_skills_count ?? 0;
  const unusedSkills = m.unused_skills_count ?? 0;
  const schemaTokens = m.tool_schema_tokens_estimate ?? 0;
  const bloatTokens = m.estimated_bloat_tokens ?? 0;
  const pinnedUnusedTools = m.pinned_unused_tools ?? [];
  const pinnedUnusedSkills = m.pinned_unused_skills ?? [];
  return (
    <div className="rounded-md border border-surface-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-text">{name}</div>
          <div className="truncate text-[11px] text-text-dim">{bot.model || bot.bot_id}</div>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${severityClass(bot.severity)}`}>
          {bot.score}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-text-muted tabular-nums">
        <span>{enrolledTools} enrolled tools</span>
        <span>{unusedTools} unused</span>
        <span>{enrolledSkills} enrolled skills</span>
        <span>{unusedSkills} unused</span>
        {schemaTokens ? (
          <span className="col-span-2">
            ~{fmtTokens(schemaTokens)} schema tokens/turn · ~{fmtTokens(bloatTokens)} bloat
          </span>
        ) : (
          <span className="col-span-2">~{fmtTokens(bloatTokens)} bloat tokens/turn</span>
        )}
      </div>
      {pinnedUnusedTools.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Pinned but never used</div>
          <div className="flex flex-wrap gap-1">
            {pinnedUnusedTools.map((name) => (
              <span
                key={name}
                className="rounded-full border border-warning/60 bg-warning/10 px-2 py-0.5 text-[10px] text-warning"
                title="Pinned in bot config but no recorded use"
              >
                📌 {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {pinnedUnusedSkills.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Pinned skills, never used</div>
          <div className="flex flex-wrap gap-1">
            {pinnedUnusedSkills.map((name) => (
              <span
                key={name}
                className="rounded-full border border-warning/60 bg-warning/10 px-2 py-0.5 text-[10px] text-warning"
              >
                📌 {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
