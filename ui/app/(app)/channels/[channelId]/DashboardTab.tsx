import { Link } from "react-router-dom";
import { LayoutDashboard } from "lucide-react";
import { CHANNEL_SLUG_PREFIX } from "@/src/stores/dashboards";
import { DashboardConfigForm } from "../../widgets/DashboardConfigForm";

interface Props {
  channelId: string;
}

export function DashboardTab({ channelId }: Props) {
  const slug = `${CHANNEL_SLUG_PREFIX}${channelId}`;
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-md bg-surface-raised border border-surface-border p-4">
        <div className="mb-3 flex items-center gap-2">
          <LayoutDashboard size={14} className="text-accent" />
          <span className="text-[13px] font-semibold text-text">
            Dashboard layout
          </span>
          <Link
            to={`/widgets/channel/${channelId}`}
            className="ml-auto text-[11px] text-accent hover:underline"
          >
            Open dashboard →
          </Link>
        </div>
        <p className="mb-4 text-[11px] text-text-dim leading-snug">
          Configure the grid preset, rail pin, tile chrome, and widget-title visibility for this channel&apos;s dashboard. Changes apply immediately across every viewer.
        </p>
        <DashboardConfigForm slug={slug} variant="tab" />
      </div>
    </div>
  );
}
