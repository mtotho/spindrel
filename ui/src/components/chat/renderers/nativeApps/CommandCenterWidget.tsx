import { Link } from "react-router-dom";

import { useCommandCenter } from "@/src/api/hooks/useCommandCenter";
import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { formatTimeUntil } from "@/src/components/spatial-canvas/spatialActivity";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";

export function CommandCenterWidget({
  envelope,
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const payload = parsePayload(envelope);
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 360,
    compactMaxHeight: 190,
    wideMinWidth: 580,
    wideMinHeight: 180,
    tallMinHeight: 280,
  });

  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Command Center"
        description="Bot assignments, next heartbeat timing, upcoming work, and recent run reports."
        t={t}
      />
    );
  }

  const { data, isLoading, isError } = useCommandCenter();
  if (isLoading) return <div style={{ color: t.textDim, fontSize: 12 }}>Loading Command Center...</div>;
  if (isError || !data) return <div style={{ color: t.textMuted, fontSize: 12 }}>Command Center is unavailable.</div>;

  const rows = data.bots.filter((bot) => bot.queue_depth > 0 || bot.upcoming.length > 0).slice(0, profile.compact ? 2 : 5);
  const first = rows[0];

  if (profile.compact) {
    return (
      <Link to="/hub/command-center" style={{ color: "inherit", textDecoration: "none" }}>
        <div style={{ display: "flex", minHeight: "100%", flexDirection: "column", gap: 10 }}>
          <div style={{ border: `1px solid ${t.surfaceBorder}`, borderRadius: 12, background: t.surface, padding: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, color: t.textDim, fontSize: 11 }}>
              <span>Assigned</span>
              <span>{data.summary.assigned}</span>
            </div>
            <div style={{ marginTop: 8, color: t.text, fontSize: 15, fontWeight: 600 }}>
              {first?.active_assignment?.title ?? "No active assignment"}
            </div>
            <div style={{ marginTop: 6, color: t.textMuted, fontSize: 12 }}>
              {first ? `${first.bot_name} · ${first.next_heartbeat_at ? formatTimeUntil(first.next_heartbeat_at) : "unscheduled"}` : `${data.summary.upcoming} upcoming`}
            </div>
          </div>
          <div style={{ color: t.textDim, fontSize: 11 }}>
            {data.summary.blocked ? `${data.summary.blocked} blocked · ` : ""}
            {data.summary.recent} recent reports
          </div>
        </div>
      </Link>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100%", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, paddingBottom: 8 }}>
        <div style={{ color: t.textDim, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Command Center
        </div>
        <Link to="/hub/command-center" style={{ color: t.accent, fontSize: 11, textDecoration: "none" }}>
          Open
        </Link>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, paddingBottom: 10 }}>
        {[
          ["Assigned", data.summary.assigned],
          ["Blocked", data.summary.blocked],
          ["Upcoming", data.summary.upcoming],
          ["Recent", data.summary.recent],
        ].map(([label, value]) => (
          <div key={label} style={{ background: t.surface, borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ color: t.textDim, fontSize: 10 }}>{label}</div>
            <div style={{ color: t.text, fontSize: 16, fontWeight: 650 }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        {rows.length ? rows.map((bot) => (
          <Link key={bot.bot_id} to="/hub/command-center" style={{ color: "inherit", textDecoration: "none" }}>
            <div style={{ borderTop: `1px solid ${t.surfaceBorder}`, padding: "8px 0", display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 10 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: t.text, fontSize: 13 }}>
                  {bot.active_assignment?.title ?? bot.bot_name}
                </div>
                <div style={{ marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: t.textMuted, fontSize: 11 }}>
                  {bot.bot_name} · {bot.queue_depth} queued
                </div>
              </div>
              <div style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
                {bot.next_heartbeat_at ? formatTimeUntil(bot.next_heartbeat_at) : "blocked"}
              </div>
            </div>
          </Link>
        )) : (
          <div style={{ color: t.textMuted, fontSize: 12 }}>No assigned work in the current window.</div>
        )}
      </div>
    </div>
  );
}
