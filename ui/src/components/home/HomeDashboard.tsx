import { Link } from "react-router-dom";
import {
  CheckCheck,
  GitMerge,
  HeartPulse,
  Inbox,
  Plus,
  Radar,
  Sparkles,
} from "lucide-react";

import { useChannels } from "../../api/hooks/useChannels";
import {
  useWorkspaceAttention,
  useWorkspaceAttentionBrief,
} from "../../api/hooks/useWorkspaceAttention";
import { useLatestHealthSummary } from "../../api/hooks/useSystemHealth";
import { useUnreadState } from "../../api/hooks/useUnread";
import { useProjectFactoryReviewInbox } from "../../api/hooks/useProjects";
import { usePageRefresh } from "../../hooks/usePageRefresh";
import { buildActionInboxModel, type ActionInboxRow, type ActionInboxTone } from "../../lib/actionInbox";
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

function toneClass(value: ActionInboxTone): string {
  if (value === "danger") return "bg-danger/10 text-danger";
  if (value === "warning") return "bg-warning/10 text-warning-muted";
  if (value === "success") return "bg-success/10 text-success";
  if (value === "info") return "bg-accent/10 text-accent";
  return "bg-surface-overlay/45 text-text-muted";
}

function rowIcon(row: ActionInboxRow) {
  if (row.kind === "replies") return row.count ? <Inbox size={15} /> : <CheckCheck size={15} />;
  if (row.kind === "project_reviews") return <GitMerge size={15} />;
  if (row.kind === "findings") return <Sparkles size={15} />;
  return <HeartPulse size={15} />;
}

function ActionInboxItem({ row, primary = false }: { row: ActionInboxRow; primary?: boolean }) {
  const body = (
    <div className={`group flex min-h-[62px] items-start gap-3 rounded-md px-3 py-3 transition-colors ${primary ? "bg-surface-overlay/40" : "bg-surface-overlay/20"} ${row.href ? "hover:bg-surface-overlay/50" : ""}`}>
      <span className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${toneClass(row.tone)}`}>
        {rowIcon(row)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="truncate text-sm font-semibold text-text">{row.title}</span>
          {row.count ? (
            <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-text-muted">
              {row.count}
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block truncate text-xs leading-5 text-text-muted">{row.detail}</span>
      </span>
    </div>
  );
  return row.href ? <Link to={row.href}>{body}</Link> : body;
}

function ActionInboxSection() {
  const { data: channels } = useChannels();
  const { data: attention } = useWorkspaceAttention();
  const { data: attentionBrief } = useWorkspaceAttentionBrief();
  const { data: health } = useLatestHealthSummary();
  const { data: unread } = useUnreadState();
  const { data: projectReviewInbox } = useProjectFactoryReviewInbox(8);
  const regularChannels = (channels ?? []).filter((ch) => !isOrchestratorClient(ch.client_id));
  const model = buildActionInboxModel({
    unreadStates: unread?.states,
    attentionItems: attention,
    attentionBrief,
    health,
    projectReviewInbox,
  });
  const primaryRow = model.rows[0] ?? {
    kind: "replies" as const,
    title: "Caught up",
    detail: "No unread replies or review-ready work.",
    count: 0,
    tone: "success" as const,
  };
  const secondaryRows = model.rows.slice(1, 5);
  const title = model.total ? `${model.total} item${model.total === 1 ? "" : "s"} need a look` : "Caught up";
  const meta = model.total
    ? `${model.unreadReplyCount} replies · ${model.actionableReviewCount} review`
    : `${regularChannels.length} channel${regularChannels.length === 1 ? "" : "s"}`;

  return (
    <AnchorSection
      testId="home-action-inbox"
      icon={model.total ? <Inbox size={14} /> : <CheckCheck size={14} />}
      eyebrow="Action Inbox"
      title={title}
      meta={meta}
      action={
        <Link to={primaryRow?.href || "/hub/attention"} className="rounded-md px-2.5 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/[0.08]">
          Open
        </Link>
      }
      emphasis="primary"
    >
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <ActionInboxItem row={primaryRow} primary />
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {secondaryRows.length ? secondaryRows.map((row) => (
            <ActionInboxItem key={row.kind} row={row} />
          )) : (
            <div className="flex min-h-[62px] items-center gap-3 rounded-md bg-surface-overlay/20 px-3 py-3">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-overlay/45 text-text-dim">
                <Radar size={15} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-text">Signals quiet</span>
                <span className="block text-xs text-text-muted">Raw Attention stays in Mission Control when you need it.</span>
              </span>
            </div>
          )}
        </div>
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
          <ActionInboxSection />
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
