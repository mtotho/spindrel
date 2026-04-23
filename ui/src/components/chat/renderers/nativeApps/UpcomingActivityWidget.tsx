import { Link } from "react-router-dom";
import { useUpcomingActivity, type UpcomingItem } from "@/src/api/hooks/useUpcomingActivity";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, parsePayload } from "./shared";

function fmtFuture(iso: string): string {
  const target = Date.parse(iso);
  if (!Number.isFinite(target)) return "--";
  const diffMs = target - Date.now();
  if (diffMs <= 0) return "now";
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  if (hours < 24) return remMinutes ? `in ${hours}h ${remMinutes}m` : `in ${hours}h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours ? `in ${days}d ${remHours}h` : `in ${days}d`;
}

function itemHref(item: UpcomingItem): string | null {
  if (item.type === "task" && item.task_id) return `/admin/tasks/${item.task_id}`;
  if (item.type === "heartbeat" && item.channel_id) return `/channels/${item.channel_id}`;
  if (item.type === "memory_hygiene") return "/admin/learning";
  return item.channel_id ? `/channels/${item.channel_id}` : null;
}

function typeLabel(item: UpcomingItem): string {
  if (item.type === "memory_hygiene") return "dreaming";
  return item.type;
}

function UpcomingRow({
  item,
  t,
}: {
  item: UpcomingItem;
  t: ThemeTokens;
}) {
  const href = itemHref(item);
  const body = (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) auto",
        gap: 10,
        alignItems: "center",
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
            {typeLabel(item)}
          </span>
          <span
            style={{
              fontSize: 13,
              color: t.text,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
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
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.channel_name ?? item.bot_name}
          </span>
          <span style={{ color: t.textDim, flexShrink: 0 }}>
            {new Date(item.scheduled_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
          </span>
        </div>
      </div>
      <div style={{ fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
        {fmtFuture(item.scheduled_at)}
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
  t,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const payload = parsePayload(envelope);
  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Upcoming Activity"
        description="Merged view of the next scheduled heartbeats, tasks, and dreaming runs."
        t={t}
      />
    );
  }

  const { data: items, isLoading, isError } = useUpcomingActivity(6);

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
        <UpcomingRow key={`${item.type}:${item.task_id ?? item.scheduled_at}`} item={item} t={t} />
      ))}
    </div>
  );
}
