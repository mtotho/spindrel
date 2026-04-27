import { Activity, Search } from "lucide-react";
import { useAgentSmell, type AgentSmellBot } from "@/src/api/hooks/useUsage";
import { openTraceInspector } from "@/src/stores/traceInspector";
import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";

function fmtNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
}

function severityTone(severity: string, t: NativeAppRendererProps["t"]) {
  if (severity === "critical") return { fg: t.danger, bg: t.dangerSubtle, border: t.dangerBorder };
  if (severity === "smelly") return { fg: t.warning, bg: t.warningSubtle, border: t.warningBorder };
  if (severity === "watch") return { fg: t.accent, bg: t.accentSubtle, border: t.accentBorder };
  return { fg: t.success, bg: t.successSubtle, border: t.successBorder };
}

function BotIcon({ bot, t }: { bot: AgentSmellBot; t: NativeAppRendererProps["t"] }) {
  const label = bot.display_name || bot.name || bot.bot_id;
  if (bot.avatar_url) {
    return (
      <img
        src={bot.avatar_url}
        alt=""
        style={{
          width: 30,
          height: 30,
          borderRadius: 999,
          objectFit: "cover",
          border: `1px solid ${t.surfaceBorder}`,
        }}
      />
    );
  }
  return (
    <span
      aria-hidden
      style={{
        width: 30,
        height: 30,
        borderRadius: 999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: t.accentSubtle,
        color: t.accent,
        border: `1px solid ${t.accentBorder}`,
        fontSize: bot.avatar_emoji ? 17 : 11,
        fontWeight: 700,
      }}
    >
      {bot.avatar_emoji || label.slice(0, 1).toUpperCase()}
    </span>
  );
}

function AgentRow({
  bot,
  compact,
  t,
}: {
  bot: AgentSmellBot;
  compact: boolean;
  t: NativeAppRendererProps["t"];
}) {
  const tone = severityTone(bot.severity, t);
  const name = bot.display_name || bot.name || bot.bot_id;
  const firstTrace = bot.traces.find((trace) => trace.correlation_id);
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        background: t.surface,
        padding: compact ? "8px 9px" : "10px 11px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
        <BotIcon bot={bot} t={t} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "baseline", minWidth: 0 }}>
            <span style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
              #{bot.rank}
            </span>
            <span
              style={{
                color: t.text,
                fontSize: 13,
                fontWeight: 650,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {name}
            </span>
          </div>
          {!compact ? (
            <div
              style={{
                color: t.textDim,
                fontSize: 11,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {bot.model || bot.bot_id}
            </div>
          ) : null}
        </div>
        <div
          style={{
            minWidth: 48,
            textAlign: "center",
            border: `1px solid ${tone.border}`,
            background: tone.bg,
            color: tone.fg,
            borderRadius: 999,
            padding: "3px 7px",
            fontSize: 12,
            fontWeight: 700,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {bot.score}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        {bot.reasons.slice(0, compact ? 2 : 3).map((reason) => {
          const reasonTone = severityTone(reason.severity, t);
          return (
            <span
              key={reason.key}
              title={reason.detail}
              style={{
                border: `1px solid ${reasonTone.border}`,
                background: reasonTone.bg,
                color: reasonTone.fg,
                borderRadius: 999,
                padding: "2px 7px",
                fontSize: 10,
                lineHeight: 1.6,
                maxWidth: "100%",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {reason.label}
            </span>
          );
        })}
      </div>

      {!compact ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 6,
              color: t.textDim,
              fontSize: 11,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            <span>{fmtNumber(bot.metrics.total_tokens)} tokens</span>
            <span>{bot.metrics.tool_calls} tools</span>
            <span>{bot.metrics.repeated_tool_calls} repeats</span>
            <span
              title={
                bot.metrics.tool_schema_tokens_estimate
                  ? `${fmtNumber(bot.metrics.tool_schema_tokens_estimate)} schema tokens/turn`
                  : "No tool_surface_summary recorded in window"
              }
            >
              {fmtNumber(bot.metrics.estimated_bloat_tokens)} bloat
            </span>
          </div>
          {(bot.metrics.pinned_unused_tools.length > 0 || bot.metrics.unused_tools_count > 0) ? (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 4,
                color: t.textMuted,
                fontSize: 10,
                lineHeight: 1.5,
              }}
            >
              {bot.metrics.unused_tools_count > 0 ? (
                <span
                  style={{
                    border: `1px solid ${t.surfaceBorder}`,
                    borderRadius: 999,
                    padding: "1px 6px",
                  }}
                  title="Tools enrolled (source=fetched) for >7 days with no recorded use"
                >
                  {bot.metrics.unused_tools_count} unused
                </span>
              ) : null}
              {bot.metrics.pinned_unused_tools.slice(0, 3).map((name) => (
                <span
                  key={name}
                  style={{
                    border: `1px solid ${t.warningBorder}`,
                    background: t.warningSubtle,
                    color: t.warning,
                    borderRadius: 999,
                    padding: "1px 6px",
                  }}
                  title="Pinned but never used — surfaces user intent that isn't paying off"
                >
                  📌 {name}
                </span>
              ))}
              {bot.metrics.pinned_unused_tools.length > 3 ? (
                <span style={{ color: t.textDim }}>
                  +{bot.metrics.pinned_unused_tools.length - 3}
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      {firstTrace ? (
        <button
          type="button"
          onClick={() => {
            if (!firstTrace.correlation_id) return;
            openTraceInspector({
              correlationId: firstTrace.correlation_id,
              title: `${name} smell evidence`,
              subtitle: firstTrace.reason,
            });
          }}
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            color: t.textMuted,
            borderRadius: 7,
            padding: "5px 7px",
            fontSize: 11,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            cursor: "pointer",
            minWidth: 0,
          }}
        >
          <span
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            <Search size={12} />
            {firstTrace.reason}
          </span>
          <span style={{ color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
            {fmtNumber(firstTrace.tokens)}
          </span>
        </button>
      ) : null}
    </div>
  );
}

export function AgentSmellWidget({
  envelope,
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const payload = parsePayload(envelope);
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 360,
    compactMaxHeight: 220,
    wideMinWidth: 640,
    wideMinHeight: 220,
    tallMinHeight: 320,
  });

  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Agent Smell"
        description="Ranks bots by suspicious trace and tool behavior."
        t={t}
      />
    );
  }

  const limit = profile.compact ? 4 : profile.tall || profile.wide ? 8 : 5;
  const { data, isLoading, isError } = useAgentSmell({ hours: 24, baseline_days: 7, limit });

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12 }}>Loading agent smell...</div>;
  }
  if (isError || !data) {
    return (
      <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.6 }}>
        Agent Smell is only available where admin usage data can be read.
      </div>
    );
  }

  const smelliest = data.bots[0];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 10,
          paddingBottom: 2,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
          <Activity size={15} color={smelliest ? severityTone(smelliest.severity, t).fg : t.textDim} />
          <span style={{ color: t.text, fontSize: 13, fontWeight: 650 }}>Agent Smell</span>
        </div>
        <span style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
          24h
        </span>
      </div>

      {data.bots.length === 0 ? (
        <div
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 8,
            background: t.surface,
            padding: 12,
            color: t.textMuted,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          No agent activity in the current window.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.bots.map((bot) => (
            <AgentRow key={bot.bot_id} bot={bot} compact={profile.compact} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}
