import { useMemo } from "react";
import type { ThemeTokens } from "@/src/theme/tokens";
import type { MCPlanStep } from "@/src/api/hooks/useMissionControl";
import { fmtElapsed } from "./planHelpers";

// ---------------------------------------------------------------------------
// Execution timeline — chronological feed of step events
// ---------------------------------------------------------------------------
interface TimelineEvent {
  time: Date;
  label: string;
  stepPosition: number;
  type: "started" | "completed" | "failed" | "skipped";
}

export function ExecutionTimeline({
  steps,
  t,
}: {
  steps: MCPlanStep[];
  t: ThemeTokens;
}) {
  const events = useMemo(() => {
    const evts: TimelineEvent[] = [];
    for (const step of steps) {
      if (step.started_at) {
        evts.push({
          time: new Date(step.started_at),
          label: `Step ${step.position} started`,
          stepPosition: step.position,
          type: "started",
        });
      }
      if (step.completed_at) {
        const type = step.status === "failed" ? "failed" : step.status === "skipped" ? "skipped" : "completed";
        evts.push({
          time: new Date(step.completed_at),
          label: `Step ${step.position} ${type}`,
          stepPosition: step.position,
          type,
        });
      }
    }
    evts.sort((a, b) => a.time.getTime() - b.time.getTime());
    return evts;
  }, [steps]);

  if (events.length === 0) return null;

  const typeColor = (type: TimelineEvent["type"]) => {
    switch (type) {
      case "started": return t.accent;
      case "completed": return t.success;
      case "failed": return t.danger;
      case "skipped": return t.textDim;
    }
  };

  const typeDot = (type: TimelineEvent["type"]) => {
    switch (type) {
      case "started": return t.accent;
      case "completed": return t.success;
      case "failed": return t.danger;
      case "skipped": return t.textDim;
    }
  };

  const fmtTimelineTime = (d: Date) => {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  // Compute elapsed since first event
  const firstTime = events[0].time.getTime();

  return (
    <div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: t.textMuted,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          marginBottom: 8,
        }}
      >
        Timeline
      </div>
      <div
        style={{
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.codeBg,
          padding: "8px 0",
        }}
      >
        {events.map((ev, i) => {
          const elapsed = ev.time.getTime() - firstTime;
          const elapsedStr = elapsed === 0 ? "" : `+${fmtElapsed(elapsed)}`;
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "5px 14px",
                position: "relative",
              }}
            >
              {/* Timeline line */}
              {i < events.length - 1 && (
                <div
                  style={{
                    position: "absolute",
                    left: 21,
                    top: 20,
                    bottom: -5,
                    width: 1,
                    background: t.surfaceBorder,
                  }}
                />
              )}
              {/* Dot */}
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: typeDot(ev.type),
                  flexShrink: 0,
                  zIndex: 1,
                }}
              />
              {/* Time */}
              <span
                style={{
                  fontSize: 10,
                  color: t.textDim,
                  fontFamily: "monospace",
                  width: 68,
                  flexShrink: 0,
                }}
              >
                {fmtTimelineTime(ev.time)}
              </span>
              {/* Event label */}
              <span style={{ fontSize: 12, color: typeColor(ev.type), fontWeight: 500, flex: 1 }}>
                {ev.label}
              </span>
              {/* Elapsed */}
              {elapsedStr && (
                <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                  {elapsedStr}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
