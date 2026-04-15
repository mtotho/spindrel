import { useState, useMemo } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { formatTime, formatDate } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  type TaskItem, STATUS_CFG,
  displayTitle, TypeBadge, TaskStatusBadge as StatusBadge, BotDot,
} from "@/src/components/shared/TaskConstants";
import { getTaskTime, isToday } from "./taskUtils";

// ---------------------------------------------------------------------------
// Current time indicator line
// ---------------------------------------------------------------------------
export function NowLine() {
  const t = useThemeTokens();
  const now = new Date();
  const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
  const pct = (minutesSinceMidnight / 1440) * 100;
  return (
    <div style={{
      position: "absolute", left: 0, right: 0, top: `${pct}%`,
      display: "flex", flexDirection: "row", alignItems: "center", zIndex: 5, pointerEvents: "none",
    }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: t.danger, marginLeft: -4 }} />
      <div style={{ flex: 1, height: 1, background: t.danger }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hour labels / grid
// ---------------------------------------------------------------------------
export function HourLabels() {
  const t = useThemeTokens();
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => {
        const pct = (h / 24) * 100;
        return (
          <div key={h} style={{
            position: "absolute", left: 0, top: `${pct}%`,
            fontSize: 10, color: t.textDim, width: 40, textAlign: "right", paddingRight: 8,
            transform: "translateY(-50%)", pointerEvents: "none",
          }}>
            {h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}
          </div>
        );
      })}
    </>
  );
}

export function HourGrid() {
  const t = useThemeTokens();
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <>
      {hours.map((h) => (
        <div key={h} style={{
          position: "absolute", left: 48, right: 0,
          top: `${(h / 24) * 100}%`,
          borderTop: `1px solid ${t.surfaceRaised}`,
          pointerEvents: "none",
        }} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Schedule conflict warning banner
// ---------------------------------------------------------------------------
export function ConflictBanner({ warnings }: { warnings: string[] }) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 8,
      padding: "8px 16px 8px 36px",
      background: t.warningSubtle,
      borderLeft: `3px solid ${t.warning}`,
    }}>
      <AlertTriangle size={14} color={t.warning} style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: t.warningMuted, marginBottom: 2 }}>
          Schedule Overlap — Schedules fire within 2 hours of each other
        </div>
        {warnings.map((w, i) => (
          <div key={i} style={{ fontSize: 10, color: t.warningMuted }}>
            {w}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Task card on timeline (Day/Week views) — simplified
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

  // Theme-aware backgrounds
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
        padding: compact ? "4px 8px" : "8px 12px", borderRadius: compact ? 6 : 8,
        background: bg,
        border: `1px solid ${borderColor}`,
        borderStyle: isVirtual ? "dashed" : "solid",
        opacity: isCancelled ? 0.4 : isVirtual ? (hovered ? 0.8 : 0.6) : (isPast && !hovered ? 0.5 : 1),
        transition: "opacity 0.15s, box-shadow 0.15s, border-color 0.15s",
        cursor: "pointer",
        boxShadow: hovered ? "0 4px 12px rgba(0,0,0,0.15)" : "none",
        zIndex: hovered ? 100 : undefined,
        ...extraStyle,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: compact ? 4 : 8 }}>
        <Icon size={compact ? 10 : 13} color={s.fg} style={{ flexShrink: 0 }} />
        <span style={{
          fontSize: compact ? 10 : 13, fontWeight: 600,
          color: isCancelled ? t.textDim : t.text,
          textDecoration: isCancelled ? "line-through" : "none",
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {displayTitle(task)}
        </span>

        {!compact && <StatusBadge status={task.status} />}

        {isRecurring && (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: t.warningSubtle, color: t.warning,
            padding: compact ? "0px 5px" : "1px 7px", borderRadius: 10,
            fontSize: compact ? 8 : 10, fontWeight: 700,
            flexShrink: 0,
          }}>
            <RefreshCw size={compact ? 7 : 9} color={t.warning} />
            {task.recurrence}
          </span>
        )}

        {!compact && (
          <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
            {time ? formatTime(time) : "\u2014"}
          </span>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: compact ? 4 : 6, marginTop: compact ? 2 : 4 }}>
        <BotDot botId={task.bot_id} size={compact ? 6 : 8} />
        <span style={{ fontSize: compact ? 9 : 10, color: t.textDim }}>{task.bot_id}</span>
        {!compact && task.task_type && <TypeBadge type={task.task_type} />}
        {compact && (
          <span style={{ fontSize: 9, color: t.textDim, marginLeft: "auto" }}>
            {time ? formatTime(time) : ""}
          </span>
        )}
      </div>
      {!compact && task.error && (
        <div style={{ fontSize: 10, color: t.danger, marginTop: 4 }}>
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
const CARD_SUPER_COMPACT_HEIGHT_PX = 28;
const CARD_MIN_GAP = 4;
/** Max minutes a card can be pushed past its natural time-of-day position */
const MAX_COLLISION_PUSH = 180;

export function DayColumn({ date, tasks, onTaskPress, compact }: { date: Date; tasks: TaskItem[]; onTaskPress: (t: TaskItem) => void; compact?: boolean }) {
  const t = useThemeTokens();
  const now = new Date();
  const showNow = isToday(date);

  const baseCardHeight = compact ? CARD_COMPACT_HEIGHT_PX : CARD_HEIGHT_PX;

  // Shrink cards dynamically when there are too many to fit in 1440px (24h)
  const effectiveCardHeight = useMemo(() => {
    if (tasks.length <= 1) return baseCardHeight;
    const available = 1440 - CARD_MIN_GAP * (tasks.length - 1);
    const fitHeight = Math.floor(available / tasks.length);
    return Math.max(CARD_SUPER_COMPACT_HEIGHT_PX, Math.min(baseCardHeight, fitHeight));
  }, [tasks.length, baseCardHeight]);

  const autoCompact = effectiveCardHeight <= CARD_COMPACT_HEIGHT_PX;

  const positioned = useMemo(() => {
    const sorted = [...tasks].sort((a, b) => getTaskTime(a).getTime() - getTaskTime(b).getTime());
    const items: { task: TaskItem; topPx: number }[] = [];

    for (const t of sorted) {
      const taskTime = getTaskTime(t);
      const naturalPos = taskTime.getHours() * 60 + taskTime.getMinutes();
      let topPx = naturalPos;

      for (const prev of items) {
        const prevBottom = prev.topPx + effectiveCardHeight + CARD_MIN_GAP;
        if (topPx < prevBottom) {
          topPx = prevBottom;
        }
      }
      // Don't push a card more than MAX_COLLISION_PUSH minutes past its real time
      topPx = Math.min(topPx, naturalPos + MAX_COLLISION_PUSH);
      // Stay within day bounds
      topPx = Math.min(topPx, 1440 - effectiveCardHeight);
      items.push({ task: t, topPx });
    }
    return items;
  }, [tasks, effectiveCardHeight]);

  return (
    <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
      <div style={{
        padding: "8px 12px", borderBottom: `1px solid ${t.surfaceOverlay}`,
        background: showNow ? t.accentSubtle : "transparent",
        position: "sticky", top: 0, zIndex: 3,
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: showNow ? t.accent : t.text }}>
          {formatDate(date)}
        </div>
        <div style={{ fontSize: 10, color: t.textDim }}>
          {tasks.length} task{tasks.length !== 1 ? "s" : ""}
        </div>
      </div>

      <div style={{ position: "relative", height: 1440, paddingLeft: 48 }}>
        <HourGrid />
        <HourLabels />
        {showNow && <NowLine />}

        {positioned.map(({ task: t, topPx }) => (
          <TaskCard
            key={t.id}
            task={t}
            isPast={getTaskTime(t) < now && t.status !== "running"}
            onClick={() => onTaskPress(t)}
            compact={autoCompact || compact}
            style={{
              position: "absolute",
              top: topPx,
              left: 52,
              right: 8,
              maxHeight: effectiveCardHeight,
              overflow: "hidden",
            }}
          />
        ))}
      </div>
    </div>
  );
}
