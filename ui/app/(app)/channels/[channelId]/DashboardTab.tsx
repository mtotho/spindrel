import { Link } from "react-router-dom";
import { LayoutDashboard } from "lucide-react";
import { CHANNEL_SLUG_PREFIX } from "@/src/stores/dashboards";
import { DashboardConfigForm } from "../../widgets/DashboardConfigForm";
import { WidgetUsefulnessSettingsSummary } from "../../widgets/WidgetUsefulnessReview";
import { Section } from "@/src/components/shared/FormControls";

interface Props {
  channelId: string;
}

export function DashboardTab({ channelId }: Props) {
  const slug = `${CHANNEL_SLUG_PREFIX}${channelId}`;
  return (
    <Section
      title={
        <span className="inline-flex items-center gap-2">
          <LayoutDashboard size={14} className="text-accent" />
          Dashboard layout
        </span>
      }
      description="Configure the grid preset, rail pin, tile chrome, and widget-title visibility for this channel's dashboard. Changes apply immediately across every viewer."
      action={
        <Link
          to={`/widgets/channel/${channelId}`}
          className="inline-flex min-h-[34px] items-center rounded-md px-2.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
        >
          Open dashboard
        </Link>
      }
    >
      <WidgetUsefulnessSettingsSummary channelId={channelId} />
      <DashboardConfigForm slug={slug} variant="tab" />
    </Section>
  );
}
