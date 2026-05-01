import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import {
  Activity,
  CalendarClock,
  Hash,
  Plus,
  Radar,
} from "lucide-react";

import { useChannels } from "../../api/hooks/useChannels";
import {
  isActiveAttentionItem,
  useWorkspaceAttention,
} from "../../api/hooks/useWorkspaceAttention";
import { useLatestHealthSummary } from "../../api/hooks/useSystemHealth";
import { useMissionControl } from "../../api/hooks/useMissionControl";
import { useUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import { usePageRefresh } from "../../hooks/usePageRefresh";
import { PageHeader } from "../layout/PageHeader";
import { RefreshableScrollView } from "../shared/RefreshableScrollView";
import { ChannelsSection } from "./sections/ChannelsSection";
import { RecentSessionsSection } from "./sections/RecentSessionsSection";
import { UnreadCenterSection } from "./sections/UnreadCenterSection";
import { UsersSection } from "./sections/UsersSection";
import { AttentionSection } from "./sections/AttentionSection";
import { DailyHealthSection } from "./sections/DailyHealthSection";
import { MissionControlSection } from "./sections/MissionControlSection";
import { UpcomingSection } from "./sections/UpcomingSection";
import { MemoryPulseSection } from "./sections/MemoryPulseSection";
import { BloatSection } from "./sections/BloatSection";

function isOrchestratorClient(clientId: string | undefined): boolean {
  return clientId === "orchestrator:home";
}

function statusTone(value: "ok" | "warn" | "danger" | "neutral"): string {
  if (value === "danger") return "border-danger/30 bg-danger/10 text-danger";
  if (value === "warn") return "border-warning/30 bg-warning/10 text-warning-muted";
  if (value === "ok") return "border-success/30 bg-success/10 text-success";
  return "border-surface-border bg-surface-raised text-text-muted";
}

function StatCard({
  icon,
  label,
  value,
  detail,
  tone = "neutral",
  href,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone?: "ok" | "warn" | "danger" | "neutral";
  href?: string;
}) {
  const body = (
    <div className="flex min-h-[112px] flex-col justify-between rounded-md border border-surface-border bg-surface-raised px-4 py-3 transition-colors hover:bg-surface-overlay/35">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase text-text-dim">{label}</span>
        <span className={`inline-flex h-8 w-8 items-center justify-center rounded-md border ${statusTone(tone)}`}>
          {icon}
        </span>
      </div>
      <div>
        <div className="text-2xl font-semibold leading-tight text-text">{value}</div>
        <div className="mt-1 truncate text-xs text-text-muted">{detail}</div>
      </div>
    </div>
  );
  return href ? <Link to={href}>{body}</Link> : body;
}

function HomeOverview() {
  const { data: channels } = useChannels();
  const { data: attention } = useWorkspaceAttention();
  const { data: health } = useLatestHealthSummary();
  const { data: missions } = useMissionControl();
  const { data: upcoming } = useUpcomingActivity(5);

  const regularChannels = (channels ?? []).filter((ch) => !isOrchestratorClient(ch.client_id));
  const activeAttention = (attention ?? []).filter(isActiveAttentionItem);
  const criticalAttention = activeAttention.filter((item) => item.severity === "critical" || item.severity === "error");
  const errorCount = health?.summary?.error_count ?? 0;
  const criticalCount = health?.summary?.critical_count ?? 0;
  const activeMissions = missions?.summary.active_missions ?? 0;
  const nextUpcoming = upcoming?.[0] ?? null;

  return (
    <section aria-label="Workspace overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        icon={<Hash size={16} />}
        label="Channels"
        value={String(regularChannels.length)}
        detail="Active workspace rooms"
      />
      <StatCard
        icon={<Radar size={16} />}
        label="Attention"
        value={activeAttention.length ? String(activeAttention.length) : "Clear"}
        detail={criticalAttention.length ? `${criticalAttention.length} urgent` : "No urgent signals"}
        tone={criticalAttention.length ? "danger" : activeAttention.length ? "warn" : "ok"}
        href="/hub/attention"
      />
      <StatCard
        icon={<Activity size={16} />}
        label="Health"
        value={criticalCount ? `${criticalCount} crit` : errorCount ? `${errorCount} err` : "Clean"}
        detail={health?.summary ? "Latest daily rollup" : "Rollup pending"}
        tone={criticalCount ? "danger" : errorCount ? "warn" : health?.summary ? "ok" : "neutral"}
        href="/hub/daily-health"
      />
      <StatCard
        icon={<CalendarClock size={16} />}
        label="Work"
        value={activeMissions ? `${activeMissions} active` : nextUpcoming ? "Scheduled" : "Quiet"}
        detail={nextUpcoming ? nextUpcoming.title : "No upcoming work found"}
        tone={activeMissions ? "warn" : "neutral"}
        href="/hub/attention"
      />
    </section>
  );
}

export function HomeDashboard() {
  const { refreshing, onRefresh } = usePageRefresh();

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Home"
        subtitle="Workspace overview"
        right={
          <div className="flex items-center gap-2">
            <Link
              to="/spatial"
              className="hidden items-center gap-1.5 rounded-md border border-surface-border px-3 py-2 text-sm font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text sm:inline-flex"
            >
              <Radar size={14} />
              Spatial
            </Link>
            <Link
              to="/channels/new"
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/[0.08]"
            >
              <Plus size={14} />
              New
            </Link>
          </div>
        }
      />
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <main className="mx-auto box-border flex w-full max-w-[1440px] flex-col gap-5 px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
          <HomeOverview />
          <div className="xl:hidden">
            <UnreadCenterSection />
          </div>
          <div className="xl:hidden">
            <UsersSection />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
            <div className="flex min-w-0 flex-col gap-5">
              <RecentSessionsSection />
              <ChannelsSection />
            </div>
            <aside className="hidden min-w-0 flex-col gap-5 xl:flex">
              <UnreadCenterSection />
              <UsersSection />
              <AttentionSection />
              <DailyHealthSection />
              <MissionControlSection />
              <UpcomingSection />
              <MemoryPulseSection />
              <BloatSection />
            </aside>
          </div>
        </main>
      </RefreshableScrollView>
    </div>
  );
}
