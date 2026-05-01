import { Link } from "react-router-dom";
import { LayoutDashboard } from "lucide-react";
import { CHANNEL_SLUG_PREFIX } from "@/src/stores/dashboards";
import { DashboardConfigForm } from "../../widgets/DashboardConfigForm";
import { WidgetUsefulnessSettingsSummary } from "../../widgets/WidgetUsefulnessReview";
import { FormRow, Section, SelectInput } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";

interface Props {
  channelId: string;
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
}

export function DashboardTab({ channelId, form, patch }: Props) {
  const slug = `${CHANNEL_SLUG_PREFIX}${channelId}`;
  return (
    <Section
      title={
        <span className="inline-flex items-center gap-2">
          <LayoutDashboard size={14} className="text-accent" />
          Workbench layout
        </span>
      }
      description="Configure the canvas preset, chat rail, tile chrome, and artifact-title visibility for this channel's workbench. Changes apply immediately across every viewer."
      action={
        <Link
          to={`/widgets/channel/${channelId}`}
          className="inline-flex min-h-[34px] items-center rounded-md px-2.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
        >
          Open workbench
        </Link>
      }
    >
      <WidgetUsefulnessSettingsSummary channelId={channelId} />
      <FormRow
        label="Bot widget agency"
        description="Controls whether bots may only propose workbench artifact improvements or also apply safe fixes."
      >
        <SelectInput
          value={(form.widget_agency_mode ?? "propose") as string}
          onChange={(v) => patch("widget_agency_mode", v as ChannelSettings["widget_agency_mode"])}
          options={[
            { label: "Propose", value: "propose" },
            { label: "Propose + fix", value: "propose_and_fix" },
          ]}
        />
      </FormRow>
      <DashboardConfigForm slug={slug} variant="tab" />
    </Section>
  );
}
