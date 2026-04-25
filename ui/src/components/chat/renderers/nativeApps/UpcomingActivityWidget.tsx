import { Link } from "react-router-dom";
import { useUpcomingActivity, type UpcomingItem } from "@/src/api/hooks/useUpcomingActivity";
import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";
import {
  formatTimeUntil,
  upcomingHref,
  upcomingTypeLabel,
} from "@/src/components/spatial-canvas/spatialActivity";

function UpcomingRow({
  item,
  stackedMeta = false,
  t,
}: {
  item: UpcomingItem;
  stackedMeta?: boolean;
  t: NativeAppRendererProps["t"];
}) {
  const href = upcomingHref(item);
  const body = (
    <div
      style={{
        display: stackedMeta ? "flex" : "grid",
        flexDirection: stackedMeta ? "column" : undefined,
        gridTemplateColumns: stackedMeta ? undefined : "minmax(0, 1fr) auto",
        gap: 10,
        alignItems: stackedMeta ? undefined : "center",
        minHeight: 42,
        padding: "8px 0",
        borderTop: `1px solid ${t.surfaceBorder}`,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", minWidth: 0 }}>
          <span
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: t.textDim,
              flexShrink: 0,
            }}
          >
            {upcomingTypeLabel(item)}
          </span>
          <span
            style={{
              fontSize: 13,
              color: t.text,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: stackedMeta ? "normal" : "nowrap",
            }}
          >
            {item.title}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "baseline",
            marginTop: 3,
            fontSize: 11,
            color: t.textMuted,
            minWidth: 0,
            flexWrap: stackedMeta ? "wrap" : "nowrap",
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: stackedMeta ? "normal" : "nowrap" }}>
            {item.channel_name ?? item.bot_name}
          </span>
          <span style={{ color: t.textDim, flexShrink: 0 }}>
            {new Date(item.scheduled_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
          </span>
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: t.textDim,
          fontVariantNumeric: "tabular-nums",
          alignSelf: stackedMeta ? "flex-start" : undefined,
        }}
      >
        {formatTimeUntil(item.scheduled_at)}
      </div>
    </div>
  );

  if (!href) return body;
  return (
    <Link to={href} style={{ color: "inherit", textDecoration: "none" }}>
      {body}
    </Link>
  );
}

export function UpcomingActivityWidget({
  envelope,
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const payload = parsePayload(envelope);
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 360,
    compactMaxHeight: 180,
    wideMinWidth: 580,
    wideMinHeight: 180,
    tallMinHeight: 280,
  });

  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Upcoming Activity"
        description="Merged view of the next scheduled heartbeats, tasks, and dreaming runs."
        t={t}
      />
    );
  }

  const itemLimit = profile.compact ? 3 : profile.wide || profile.tall ? 6 : 4;
  const { data: items, isLoading, isError } = useUpcomingActivity(itemLimit);

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12 }}>Loading upcoming activity…</div>;
  }
  if (isError) {
    return (
      <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.6 }}>
        Upcoming activity is available where admin scheduling data can be read.
      </div>
    );
  }
  if (!items?.length) {
    return <div style={{ color: t.textMuted, fontSize: 12 }}>Nothing scheduled.</div>;
  }

  if (profile.compact) {
    const next = items[0];
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: "100%" }}>
        <div
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 12,
            background: t.surface,
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
            <span
              style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: t.textDim,
              }}
            >
              Up next
            </span>
            <span style={{ fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
              {formatTimeUntil(next.scheduled_at)}
            </span>
          </div>
          <div style={{ color: t.text, fontSize: 14, fontWeight: 600, lineHeight: 1.35 }}>
            {next.title}
          </div>
          <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.5 }}>
            {upcomingTypeLabel(next)} · {next.channel_name ?? next.bot_name} · {new Date(next.scheduled_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
          </div>
        </div>
        <div style={{ fontSize: 11, color: t.textDim }}>
          {items.length > 1 ? `${items.length - 1} more item${items.length === 2 ? "" : "s"} queued.` : "Only one item scheduled."}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", paddingBottom: 8 }}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: t.textDim,
          }}
        >
          Next Window
        </div>
        <div style={{ fontSize: 11, color: t.textMuted, fontVariantNumeric: "tabular-nums" }}>
          {items.length} items
        </div>
      </div>
      {items.map((item) => (
        <UpcomingRow
          key={`${item.type}:${item.task_id ?? item.scheduled_at}`}
          item={item}
          stackedMeta={profile.tall}
          t={t}
        />
      ))}
    </div>
  );
}
