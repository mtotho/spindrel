import { Link } from "react-router-dom";

import { useMissionControl } from "@/src/api/hooks/useMissionControl";
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
        title="Mission Control"
        description="Mission load, bot lanes, attention signals, and spatial readiness."
        t={t}
      />
    );
  }

  const { data, isLoading, isError } = useMissionControl();
  if (isLoading) return <div style={{ color: t.textDim, fontSize: 12 }}>Loading Mission Control...</div>;
  if (isError || !data) return <div style={{ color: t.textMuted, fontSize: 12 }}>Mission Control is unavailable.</div>;

  const rows = data.lanes.filter((bot) => bot.missions.length > 0 || bot.attention_signals.length > 0).slice(0, profile.compact ? 2 : 5);
  const first = rows[0];

  if (profile.compact) {
    return (
      <Link to="/hub/mission-control" style={{ color: "inherit", textDecoration: "none" }}>
        <div style={{ display: "flex", minHeight: "100%", flexDirection: "column", gap: 10 }}>
          <div style={{ border: `1px solid ${t.surfaceBorder}`, borderRadius: 12, background: t.surface, padding: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, color: t.textDim, fontSize: 11 }}>
              <span>Missions</span>
              <span>{data.summary.active_missions}</span>
            </div>
            <div style={{ marginTop: 8, color: t.text, fontSize: 15, fontWeight: 600 }}>
              {first?.missions[0]?.mission.title ?? "No active mission"}
            </div>
            <div style={{ marginTop: 6, color: t.textMuted, fontSize: 12 }}>
              {first ? `${first.bot_name} · ${first.missions[0]?.mission.next_run_at ? formatTimeUntil(first.missions[0].mission.next_run_at) : "manual"}` : `${data.summary.attention_signals} attention`}
            </div>
          </div>
          <div style={{ color: t.textDim, fontSize: 11 }}>
            {data.summary.spatial_warnings ? `${data.summary.spatial_warnings} spatial warnings · ` : ""}
            {data.summary.recent_updates} recent updates
          </div>
        </div>
      </Link>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100%", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, paddingBottom: 8 }}>
        <div style={{ color: t.textDim, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Mission Control
        </div>
        <Link to="/hub/mission-control" style={{ color: t.accent, fontSize: 11, textDecoration: "none" }}>
          Open
        </Link>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, paddingBottom: 10 }}>
        {[
          ["Active", data.summary.active_missions],
          ["Bots", data.summary.active_bots],
          ["Spatial", data.summary.spatial_warnings],
          ["Attention", data.summary.attention_signals],
        ].map(([label, value]) => (
          <div key={label} style={{ background: t.surface, borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ color: t.textDim, fontSize: 10 }}>{label}</div>
            <div style={{ color: t.text, fontSize: 16, fontWeight: 650 }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        {rows.length ? rows.map((bot) => (
          <Link key={bot.bot_id} to="/hub/mission-control" style={{ color: "inherit", textDecoration: "none" }}>
            <div style={{ borderTop: `1px solid ${t.surfaceBorder}`, padding: "8px 0", display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 10 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: t.text, fontSize: 13 }}>
                  {bot.missions[0]?.mission.title ?? bot.bot_name}
                </div>
                <div style={{ marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: t.textMuted, fontSize: 11 }}>
                  {bot.bot_name} · {bot.missions.length} missions · {bot.warning_count} warnings
                </div>
              </div>
              <div style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
                {bot.missions[0]?.mission.next_run_at ? formatTimeUntil(bot.missions[0].mission.next_run_at) : "manual"}
              </div>
            </div>
          </Link>
        )) : (
          <div style={{ color: t.textMuted, fontSize: 12 }}>No active mission lanes.</div>
        )}
      </div>
    </div>
  );
}
