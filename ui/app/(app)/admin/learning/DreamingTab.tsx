import { useMemo, useState } from "react";
import { AlertTriangle, Moon } from "lucide-react";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import { Section } from "@/src/components/shared/FormControls";
import {
  EmptyState,
  InfoBanner,
  SettingsSegmentedControl,
  SettingsStatGrid,
} from "@/src/components/shared/SettingsControls";
import type { BotConfig } from "@/src/types/api";

type RunFilter = "all" | "memory_hygiene" | "skill_review";

export function DreamingTab() {
  const { data, isLoading } = useLearningOverview();
  const { data: bots } = useAdminBots();
  const [runFilter, setRunFilter] = useState<RunFilter>("all");

  const botConfigMap = useMemo(() => {
    const map: Record<string, BotConfig> = {};
    if (bots) for (const bot of bots) map[bot.id] = bot;
    return map;
  }, [bots]);

  const filteredRuns = useMemo(() => {
    if (!data?.recent_runs) return [];
    if (runFilter === "all") return data.recent_runs;
    return data.recent_runs.filter((run) => run.job_type === runFilter);
  }, [data?.recent_runs, runFilter]);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-20 rounded-md bg-surface-raised/35" />
        <div className="h-48 rounded-md bg-surface-raised/35" />
      </div>
    );
  }

  if (!data) return <EmptyState message="Dreaming data is not available." />;

  const maintenanceEnabled = data.bots.filter((bot) => bot.enabled).length;
  const skillReviewEnabled = data.bots.filter((bot) => bot.skill_review_enabled).length;
  const failures = data.bots.filter(
    (bot) => bot.last_task_status === "failed" || bot.skill_review_last_task_status === "failed",
  );

  return (
    <div className="flex flex-col gap-7">
      <InfoBanner variant="info" icon={<Moon size={13} />}>
        Dreaming is the background maintenance surface for memory hygiene and skill review. Global defaults live in{" "}
        <a href="/settings/system#Memory%20%26%20Context" className="font-semibold text-accent hover:underline">
          Settings / Memory &amp; Context
        </a>
        .
      </InfoBanner>

      <Section title="Dreaming Status" description="Per-bot maintenance and skill-review enablement.">
        <SettingsStatGrid
          items={[
            { label: "Maintenance", value: `${maintenanceEnabled}/${data.bots.length}`, tone: maintenanceEnabled ? "warning" : "default" },
            { label: "Skill review", value: `${skillReviewEnabled}/${data.bots.length}`, tone: skillReviewEnabled ? "accent" : "default" },
            { label: "Recent runs", value: data.recent_runs.length },
            { label: "Failures", value: failures.length, tone: failures.length ? "danger" : "success" },
          ]}
        />
        {failures.length > 0 && (
          <InfoBanner variant="danger" icon={<AlertTriangle size={13} />}>
            Last run failed for {failures.map((bot) => bot.bot_name).join(", ")}.
          </InfoBanner>
        )}
      </Section>

      <Section title="Dreaming by Bot" description="Toggle background jobs per bot. Inherit uses the global default.">
        <DreamingBotTable bots={data.bots} mode="manage" botConfigMap={botConfigMap} />
      </Section>

      <Section
        title="Recent Runs"
        description="Background run logs for memory maintenance and skill review."
        action={
          <SettingsSegmentedControl
            value={runFilter}
            onChange={setRunFilter}
            options={[
              { value: "all", label: "All" },
              { value: "memory_hygiene", label: "Maintenance" },
              { value: "skill_review", label: "Skill Review" },
            ]}
          />
        }
      >
        {filteredRuns.length === 0 ? (
          <EmptyState message="No dreaming runs in this window." />
        ) : (
          <HygieneHistoryList runs={filteredRuns} showBotName />
        )}
      </Section>
    </div>
  );
}
