import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import {
  Activity,
  CalendarClock,
  CheckCheck,
  GitMerge,
  MessageSquareWarning,
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
import { useUnreadState } from "../../api/hooks/useUnread";
import { useProjectFactoryReviewInbox } from "../../api/hooks/useProjects";
import { usePageRefresh } from "../../hooks/usePageRefresh";
import { PageHeader } from "../layout/PageHeader";
import { RefreshableScrollView } from "../shared/RefreshableScrollView";
import { AnchorSection } from "../shared/AnchorSection";
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
  if (value === "danger") return "bg-danger/10 text-danger";
  if (value === "warn") return "bg-warning/10 text-warning-muted";
  if (value === "ok") return "bg-success/10 text-success";
  return "bg-surface-overlay/45 text-text-muted";
}

function PulseItem({
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
    <div className="group flex min-h-[76px] items-start gap-3 rounded-md bg-surface-overlay/25 px-3 py-3 transition-colors hover:bg-surface-overlay/45">
      <span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${statusTone(tone)}`}>
          {icon}
      </span>
      <div className="min-w-0">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-text">{value}</span>
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">{label}</span>
        </div>
        <div className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{detail}</div>
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
  const { data: unread } = useUnreadState();

  const regularChannels = (channels ?? []).filter((ch) => !isOrchestratorClient(ch.client_id));
  const activeAttention = (attention ?? []).filter(isActiveAttentionItem);
  const criticalAttention = activeAttention.filter((item) => item.severity === "critical" || item.severity === "error");
  const unreadSessions = (unread?.states ?? []).filter((state) => state.unread_agent_reply_count > 0);
  const unreadCount = unreadSessions.reduce((sum, state) => sum + state.unread_agent_reply_count, 0);
  const errorCount = health?.summary?.error_count ?? 0;
  const criticalCount = health?.summary?.critical_count ?? 0;
  const activeMissions = missions?.summary.active_missions ?? 0;
  const nextUpcoming = upcoming?.[0] ?? null;

  return (
    <AnchorSection
      testId="home-workspace-pulse"
      icon={<Activity size={14} />}
      eyebrow="Workspace pulse"
      title="What needs a look"
      meta={`${regularChannels.length} channel${regularChannels.length === 1 ? "" : "s"}`}
      action={
        <Link to="/hub/attention" className="rounded-md px-2.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/[0.08]">
          Review
        </Link>
      }
      emphasis="primary"
    >
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <PulseItem
          icon={<Radar size={16} />}
          label="Attention"
          value={activeAttention.length ? `${activeAttention.length} active` : "Clear"}
          detail={criticalAttention.length ? `${criticalAttention.length} urgent finding${criticalAttention.length === 1 ? "" : "s"}` : "No urgent signals"}
          tone={criticalAttention.length ? "danger" : activeAttention.length ? "warn" : "ok"}
          href="/hub/attention"
        />
        <PulseItem
          icon={<CheckCheck size={16} />}
          label="Unread"
          value={unreadCount ? `${unreadCount} ${unreadCount === 1 ? "reply" : "replies"}` : "Caught up"}
          detail={unreadSessions.length ? `${unreadSessions.length} session${unreadSessions.length === 1 ? "" : "s"} with unread agent replies` : "No unread agent replies"}
          tone={unreadCount ? "warn" : "ok"}
        />
        <PulseItem
          icon={<Activity size={16} />}
          label="Health"
          value={criticalCount ? `${criticalCount} crit` : errorCount ? `${errorCount} err` : "Clean"}
          detail={health?.summary ? "Latest daily rollup" : "Rollup pending"}
          tone={criticalCount ? "danger" : errorCount ? "warn" : health?.summary ? "ok" : "neutral"}
          href="/hub/daily-health"
        />
        <PulseItem
          icon={<CalendarClock size={16} />}
          label="Work"
          value={activeMissions ? `${activeMissions} active` : nextUpcoming ? "Scheduled" : "Quiet"}
          detail={nextUpcoming ? nextUpcoming.title : "No upcoming work found"}
          tone={activeMissions ? "warn" : "neutral"}
          href="/hub/attention"
        />
      </div>
    </AnchorSection>
  );
}

function reviewStateLabel(state: string | undefined) {
  return String(state || "needs_review").replaceAll("_", " ");
}

function ProjectFactoryPulseSection() {
  const { data: inbox } = useProjectFactoryReviewInbox(8);
  const items = inbox?.items ?? [];
  const needsAttention = inbox?.summary?.needs_attention_count ?? items.filter((item) => item.state !== "reviewed" && item.state !== "reviewing").length;
  if (!needsAttention) return null;
  const topItems = items.slice(0, 3);

  return (
    <AnchorSection
      testId="home-project-factory-pulse"
      icon={<GitMerge size={14} />}
      eyebrow="Project Factory"
      title="Runs waiting for review"
      meta={`${needsAttention} need${needsAttention === 1 ? "s" : ""} attention`}
      action={
        topItems[0]?.links?.project_runs_url ? (
          <Link to={topItems[0].links.project_runs_url} className="rounded-md px-2.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/[0.08]">
            Open
          </Link>
        ) : null
      }
      emphasis="secondary"
    >
      <div className="flex flex-col gap-1">
        {topItems.map((item) => (
          <Link
            key={item.id}
            to={item.links?.run_url || item.links?.project_runs_url || `/admin/projects/${item.project_id}#Runs`}
            className="group flex min-h-[58px] items-start gap-3 rounded-md px-2.5 py-2 transition-colors hover:bg-surface-overlay/35"
          >
            <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-warning/10 text-warning-muted">
              <MessageSquareWarning size={14} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="truncate text-sm font-semibold text-text">{item.title}</span>
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">{reviewStateLabel(item.state)}</span>
              </span>
              <span className="mt-0.5 block truncate text-xs text-text-muted">
                {item.project_name} · {item.next_action || item.summary_line || "Review run evidence"}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </AnchorSection>
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
        chrome="flow"
        right={
          <div className="flex items-center gap-2">
            <Link
              to="/spatial"
              className="hidden items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text sm:inline-flex"
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
        <main className="box-border flex w-full max-w-[1600px] flex-col gap-5 px-4 py-4 sm:px-6 lg:px-8 lg:py-5">
          <HomeOverview />
          <ProjectFactoryPulseSection />
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
