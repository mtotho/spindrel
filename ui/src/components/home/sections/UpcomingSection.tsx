import { Activity, Calendar, ChevronRight, Clock, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import { useUpcomingActivity, type UpcomingItem } from "../../../api/hooks/useUpcomingActivity";
import { SectionHeading } from "./SectionHeading";

const MAX_ITEMS = 3;

function formatTimeUntil(scheduledAt: string, now = Date.now()): string {
  const ts = new Date(scheduledAt).getTime();
  if (Number.isNaN(ts)) return "";
  const diffMs = ts - now;
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 0) return "overdue";
  if (minutes < 1) return "now";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  const days = Math.round(hours / 24);
  return `in ${days}d`;
}

function typeIcon(type: UpcomingItem["type"]): ReactNode {
  if (type === "heartbeat") return <Activity size={14} />;
  if (type === "memory_hygiene") return <Sparkles size={14} />;
  return <Clock size={14} />;
}

function typeLabel(type: UpcomingItem["type"]): string {
  if (type === "heartbeat") return "Heartbeat";
  if (type === "memory_hygiene") return "Hygiene";
  return "Task";
}

function itemHref(item: UpcomingItem): string {
  if (item.channel_id) return `/channels/${item.channel_id}`;
  if (item.bot_id) return `/admin/bots/${encodeURIComponent(item.bot_id)}`;
  return "/";
}

/**
 * Next few scheduled tasks / heartbeats / memory hygiene runs. Mobile
 * mirror of the Now Well's orbit ring, compressed to a sortable list of
 * the soonest items.
 */
export function UpcomingSection() {
  const { data } = useUpcomingActivity(MAX_ITEMS);
  const items = data ?? [];
  if (items.length === 0) return null;

  const now = Date.now();

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Calendar size={14} />} label="Upcoming" />
      <div className="flex flex-col gap-1">
        {items.map((item, idx) => {
          const minutesUntil = (new Date(item.scheduled_at).getTime() - now) / 60000;
          const imminent = minutesUntil >= 0 && minutesUntil < 60;
          return (
            <Link
              key={`${item.type}-${item.bot_id}-${item.scheduled_at}-${idx}`}
              to={itemHref(item)}
              className="group flex min-h-[56px] items-center gap-3 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45"
            >
              <span className={imminent ? "text-warning-muted" : "text-text-dim"}>
                {typeIcon(item.type)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-text">{item.title}</div>
                <div className="truncate text-xs text-text-dim">
                  {typeLabel(item.type)}
                  {item.channel_name ? ` · ${item.channel_name}` : ""}
                  {!item.channel_name && item.bot_name ? ` · ${item.bot_name}` : ""}
                </div>
              </div>
              <span
                className={`shrink-0 text-xs tabular-nums ${
                  imminent ? "text-warning-muted" : "text-text-dim"
                }`}
              >
                {formatTimeUntil(item.scheduled_at, now)}
              </span>
              <ChevronRight
                size={14}
                className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
              />
            </Link>
          );
        })}
      </div>
    </section>
  );
}
