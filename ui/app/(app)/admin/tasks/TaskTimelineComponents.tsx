import { useState, useMemo } from "react";
import { RefreshCw, AlertTriangle, ChevronRight } from "lucide-react";
import { formatTime, formatDate } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  type TaskItem, STATUS_CFG, TYPE_BADGE_COLORS,
  displayTitle, TypeBadge, TaskStatusBadge as StatusBadge, BotDot,
} from "@/src/components/shared/TaskConstants";
import { getTaskTime, isToday } from "./taskUtils";

// ---------------------------------------------------------------------------
// Current time indicator line
// ---------------------------------------------------------------------------
export function NowLine() {
  const now = new Date();
  const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
  const pct = (minutesSinceMidnight / 1440) * 100;
  const timeStr = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return (
    <div
      className="flex absolute left-0 right-0 flex-row items-center z-[5] pointer-events-none"
      style={{ top: `${pct}%` }}
    >
      <div className="w-2.5 h-2.5 rounded-full bg-danger -ml-[5px] shadow-[0_0_6px_rgb(var(--color-danger))]" />
      <div className="flex-1 h-[1.5px] bg-danger/70" />
      <span className="text-[9px] text-danger font-bold px-1.5 bg-surface rounded-sm">{timeStr}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hour labels / grid
// ---------------------------------------------------------------------------
export function HourLabels() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => {
        const pct = (h / 24) * 100;
        return (
          <div key={h} className="absolute left-0 text-[10px] text-text-dim w-10 text-right pr-2 pointer-events-none -translate-y-1/2" style={{ top: `${pct}%` }}>
            {h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}
          </div>
        );
      })}
    </>
  );
}

export function HourGrid() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => (
        <div
          key={h}
          className="absolute left-12 right-0 border-t border-surface-border/30 pointer-events-none"
          style={{ top: `${(h / 24) * 100}%` }}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Schedule conflict warning banner
// ---------------------------------------------------------------------------
export function ConflictBanner({ warnings }: { warnings: string[] }) {
  return (
    <div className="flex flex-row items-start gap-2 px-4 py-2 pl-9 bg-warning/[0.08] border-l-[3px] border-l-warning">
      <AlertTriangle size={14} className="text-warning shrink-0 mt-px" />
      <div className="flex-1 min-w-0">
        <div className="text-[11px] font-bold text-warning-muted mb-0.5">
          Schedule Overlap — Schedules fire within 2 hours of each other
        </div>
        {warnings.map((w, i) => (
          <div key={i} className="text-[10px] text-warning-muted">
            {w}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Task card on timeline (Day/Week views)
// ---------------------------------------------------------------------------
export function TaskCard({
  task, isPast, onClick, compact, style: extraStyle,
}: {
  task: TaskItem; isPast: boolean; onClick: () => void; compact?: boolean; style?: React.CSSProperties;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const isVirtual = task.is_virtual;
  const isCancelled = task.status === "cancelled";
  const s = STATUS_CFG[task.status] || STATUS_CFG.pending;
  const Icon = s.icon;
  const isRecurring = !!task.recurrence;
  const time = task.scheduled_at || task.created_at;

  // Theme-aware backgrounds — still inline since they depend on multiple runtime states
  const cancelledBg = hovered ? t.surfaceOverlay : t.surface;
  const virtualBg = hovered ? t.surfaceOverlay : t.accentMuted;
  const normalBg = hovered ? t.surfaceOverlay : isPast ? t.inputBg : t.surfaceRaised;
  const bg = isCancelled ? cancelledBg : isVirtual ? virtualBg : normalBg;
  const borderColor = isCancelled
    ? t.surfaceRaised
    : isVirtual
    ? (hovered ? t.accent : t.surfaceBorder)
    : hovered ? t.accent : isPast ? t.surfaceRaised : t.surfaceOverlay;

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: compact ? "4px 8px" : "8px 12px",
        borderRadius: compact ? 6 : 8,
        background: bg,
        border: `1px solid ${borderColor}`,
        borderLeft: `3px solid ${(TYPE_BADGE_COLORS[task.task_type ?? "agent"] || TYPE_BADGE_COLORS.agent)?.fg || borderColor}`,
        borderStyle: isVirtual ? "dashed" : "solid",
        opacity: isCancelled ? 0.35 : isVirtual ? (hovered ? 0.85 : 0.55) : (isPast && !hovered ? 0.45 : 1),
        transition: "opacity 0.2s, box-shadow 0.2s, border-color 0.2s, transform 0.15s",
        cursor: "pointer",
        boxShadow: hovered ? "0 6px 20px rgba(0,0,0,0.2)" : "0 1px 3px rgba(0,0,0,0.06)",
        zIndex: hovered ? 100 : undefined,
        transform: hovered ? "translateY(-1px)" : "none",
        ...extraStyle,
      }}
    >
      <div className={`flex flex-row items-center ${compact ? "gap-1" : "gap-2"}`}>
        <Icon size={compact ? 10 : 13} color={s.fg} className="shrink-0" />
        <span className={`${compact ? "text-[10px]" : "text-[13px]"} font-semibold ${isCancelled ? "text-text-dim line-through" : "text-text"} flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap`}>
          {displayTitle(task)}
        </span>

        {!compact && <StatusBadge status={task.status} />}

        {isRecurring && (
          <span className={`inline-flex flex-row items-center gap-[3px] bg-warning/[0.08] text-warning ${compact ? "px-[5px] text-[8px]" : "px-[7px] py-px text-[10px]"} rounded-full font-bold shrink-0`}>
            <RefreshCw size={compact ? 7 : 9} className="text-warning" />
            {task.recurrence}
          </span>
        )}

        {!compact && (
          <span className="text-[11px] text-text-dim shrink-0">
            {time ? formatTime(time) : "\u2014"}
          </span>
        )}
      </div>

      <div className={`flex flex-row items-center ${compact ? "gap-1 mt-0.5" : "gap-1.5 mt-1"}`}>
        <BotDot botId={task.bot_id} size={compact ? 6 : 8} />
        <span className={`${compact ? "text-[9px]" : "text-[10px]"} text-text-dim`}>{task.bot_id}</span>
        {!compact && task.task_type && <TypeBadge type={task.task_type} />}
        {compact && (
          <span className="text-[9px] text-text-dim ml-auto">
            {time ? formatTime(time) : ""}
          </span>
        )}
      </div>
      {!compact && task.error && (
        <div className="text-[10px] text-danger mt-1">
          {task.error.substring(0, 100)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day column
// ---------------------------------------------------------------------------
const CARD_HEIGHT_PX = 70;
const CARD_COMPACT_HEIGHT_PX = 46;
const CARD_SUPER_COMPACT_HEIGHT_PX = 36;
const CARD_MIN_GAP = 4;

/** Lane-based layout: assign overlapping cards to side-by-side lanes (like Google Calendar). */
function assignLanes(sorted: { task: TaskItem; topPx: number }[], cardHeight: number): { task: TaskItem; topPx: number; lane: number; totalLanes: number }[] {
  const items: { task: TaskItem; topPx: number; lane: number; bottomPx: number }[] = [];

  for (const { task, topPx } of sorted) {
    const bottomPx = topPx + cardHeight;
    let lane = 0;
    while (items.some((prev) => prev.lane === lane && prev.bottomPx + CARD_MIN_GAP > topPx)) {
      lane++;
    }
    items.push({ task, topPx, lane, bottomPx });
  }

  const result: { task: TaskItem; topPx: number; lane: number; totalLanes: number }[] = [];
  const visited = new Set<number>();

  for (let i = 0; i < items.length; i++) {
    if (visited.has(i)) continue;
    const group: number[] = [];
    const queue = [i];
    visited.add(i);
    while (queue.length > 0) {
      const idx = queue.shift()!;
      group.push(idx);
      for (let j = 0; j < items.length; j++) {
        if (visited.has(j)) continue;
        if (items[idx].topPx < items[j].bottomPx + CARD_MIN_GAP && items[j].topPx < items[idx].bottomPx + CARD_MIN_GAP) {
          visited.add(j);
          queue.push(j);
        }
      }
    }
    const maxLane = Math.max(...group.map((g) => items[g].lane)) + 1;
    for (const g of group) {
      result.push({ task: items[g].task, topPx: items[g].topPx, lane: items[g].lane, totalLanes: maxLane });
    }
  }

  return result;
}

export function DayColumn({ date, tasks, onTaskPress, compact, showHourLabels = true }: { date: Date; tasks: TaskItem[]; onTaskPress: (t: TaskItem) => void; compact?: boolean; showHourLabels?: boolean }) {
  const now = new Date();
  const showNow = isToday(date);

  const baseCardHeight = compact ? CARD_COMPACT_HEIGHT_PX : CARD_HEIGHT_PX;

  const effectiveCardHeight = useMemo(() => {
    if (tasks.length <= 1) return baseCardHeight;
    const available = 1440 - CARD_MIN_GAP * (tasks.length - 1);
    const fitHeight = Math.floor(available / tasks.length);
    return Math.max(CARD_SUPER_COMPACT_HEIGHT_PX, Math.min(baseCardHeight, fitHeight));
  }, [tasks.length, baseCardHeight]);

  const autoCompact = effectiveCardHeight <= CARD_COMPACT_HEIGHT_PX;

  const positioned = useMemo(() => {
    const sorted = [...tasks]
      .sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime())
      .map((task) => {
        const taskTime = getTaskTime(task);
        const topPx = taskTime.getHours() * 60 + taskTime.getMinutes();
        return { task, topPx: Math.min(topPx, 1440 - effectiveCardHeight) };
      });
    return assignLanes(sorted, effectiveCardHeight);
  }, [tasks, effectiveCardHeight]);

  return (
    <div className="flex-1 min-w-0 relative">
      <div className={`flex flex-row items-baseline justify-between px-3.5 py-2.5 border-b border-surface-overlay sticky top-0 z-[3] ${showNow ? "bg-accent/[0.06]" : "bg-transparent"}`}>
        <div className={`text-xs font-semibold ${showNow ? "text-accent" : "text-text"}`}>
          {formatDate(date)}
        </div>
        <div className={`text-[10px] font-medium ${showNow ? "text-accent/80" : "text-text-dim"}`}>
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
        </div>
      </div>

      <div className="relative pl-12" style={{ height: 1440 }}>
        <HourGrid />
        {showHourLabels && <HourLabels />}
        {showNow && <NowLine />}

        {positioned.map(({ task: tk, topPx, lane, totalLanes }) => {
          const contentWidth = `calc(100% - 60px)`;
          const laneWidth = `calc(${contentWidth} / ${totalLanes})`;
          const laneLeft = `calc(52px + (${contentWidth} / ${totalLanes}) * ${lane})`;
          return (
            <TaskCard
              key={tk.id}
              task={tk}
              isPast={getTaskTime(tk) < now && tk.status !== "running"}
              onClick={() => onTaskPress(tk)}
              compact={autoCompact || compact}
              style={{
                position: "absolute",
                top: topPx,
                left: laneLeft,
                width: `calc(${laneWidth} - ${CARD_MIN_GAP}px)`,
                maxHeight: effectiveCardHeight,
                overflow: "hidden",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mobile week summary — replaces the 7-column grid on narrow screens
// ---------------------------------------------------------------------------
export function MobileWeekSummary({ tasksByDay, onDayPress, onTaskPress }: {
  tasksByDay: Record<string, TaskItem[]>;
  onDayPress: (date: Date) => void;
  onTaskPress: (t: TaskItem) => void;
}) {
  const now = new Date();
  return (
    <div className="flex flex-col">
      {Object.entries(tasksByDay).map(([dayStr, tasks]) => {
        const date = new Date(dayStr);
        const today = isToday(date);
        return (
          <div key={dayStr} className={today ? "bg-accent/[0.04]" : ""}>
            <button
              onClick={() => onDayPress(date)}
              className={`flex flex-row items-center justify-between w-full px-4 py-3 bg-transparent border-none border-b border-surface-border cursor-pointer`}
            >
              <span className={`text-sm font-bold ${today ? "text-accent" : "text-text"}`}>
                {today ? "Today" : date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
              </span>
              <div className="flex flex-row items-center gap-2">
                <span className={`text-xs font-medium ${tasks.length > 0 ? "text-text-muted" : "text-text-dim"}`}>
                  {tasks.length} task{tasks.length !== 1 ? "s" : ""}
                </span>
                <ChevronRight size={14} className="text-text-dim" />
              </div>
            </button>
            {tasks.length > 0 && (
              <div className="flex flex-col gap-2 px-4 py-2">
                {tasks.slice(0, 3).map((tk) => (
                  <TaskCard
                    key={tk.id}
                    task={tk}
                    isPast={getTaskTime(tk) < now && tk.status !== "running"}
                    onClick={() => onTaskPress(tk)}
                    compact
                  />
                ))}
                {tasks.length > 3 && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onDayPress(date); }}
                    className="text-[11px] text-accent bg-transparent border-none cursor-pointer py-1"
                  >
                    +{tasks.length - 3} more
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
