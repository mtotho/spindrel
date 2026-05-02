import type {
  AttentionBriefResponse,
  OperatorTriageState,
  WorkspaceAttentionItem,
} from "../api/hooks/useWorkspaceAttention.ts";
import type { SessionReadState } from "../api/hooks/useUnread.ts";
import type { ProjectFactoryReviewInbox, ProjectFactoryReviewInboxItem } from "../types/api.ts";

export type ActionInboxTone = "neutral" | "success" | "warning" | "danger" | "info";
export type ActionInboxKind = "replies" | "project_reviews" | "findings" | "health";

export interface ActionInboxRow {
  kind: ActionInboxKind;
  title: string;
  detail: string;
  count: number;
  href?: string;
  tone: ActionInboxTone;
}

export interface ActionInboxModel {
  total: number;
  unreadReplyCount: number;
  actionableReviewCount: number;
  projectReviewCount: number;
  findingsCount: number;
  healthCount: number;
  rows: ActionInboxRow[];
  projectReviewItems: ProjectFactoryReviewInboxItem[];
  findingItems: WorkspaceAttentionItem[];
}

export interface ActionInboxInput {
  unreadStates?: SessionReadState[] | null;
  attentionItems?: WorkspaceAttentionItem[] | null;
  projectReviewInbox?: ProjectFactoryReviewInbox | null;
  attentionBrief?: AttentionBriefResponse | null;
  health?: { summary?: { error_count?: number; critical_count?: number } | null } | null;
}

function plural(count: number, singular: string, pluralValue = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralValue}`;
}

function isActiveAttentionItem(item: WorkspaceAttentionItem): boolean {
  return item.status !== "resolved" && item.status !== "acknowledged";
}

function getOperatorTriage(item: WorkspaceAttentionItem): OperatorTriageState | null {
  const triage = item.evidence?.operator_triage;
  return triage && typeof triage === "object" ? triage as OperatorTriageState : null;
}

export function isActionableProjectReviewItem(item: ProjectFactoryReviewInboxItem): boolean {
  return !["reviewed", "reviewing", "follow_up_running"].includes(String(item.state));
}

export function isDecisionReadyAttentionFinding(item: WorkspaceAttentionItem): boolean {
  if (!isActiveAttentionItem(item)) return false;
  const triage = getOperatorTriage(item);
  return triage?.state === "ready_for_review" || triage?.review_required === true;
}

export function buildActionInboxModel(input: ActionInboxInput): ActionInboxModel {
  const unreadRows = (input.unreadStates ?? []).filter((row) => row.unread_agent_reply_count > 0);
  const unreadReplyCount = unreadRows.reduce((sum, row) => sum + row.unread_agent_reply_count, 0);
  const attentionItems = input.attentionItems ?? [];
  const projectReviewItems = (input.projectReviewInbox?.items ?? []).filter(isActionableProjectReviewItem);
  const projectReviewCount = input.projectReviewInbox?.summary?.needs_attention_count ?? projectReviewItems.length;
  const findingItems = attentionItems.filter(isDecisionReadyAttentionFinding);
  const briefCounts = input.attentionBrief?.summary;
  const findingsCount = findingItems.length + (briefCounts?.autofix ?? 0) + (briefCounts?.decisions ?? 0);
  const criticalHealth = input.health?.summary?.critical_count ?? 0;
  const errorHealth = input.health?.summary?.error_count ?? 0;
  const healthCount = criticalHealth + errorHealth;
  const actionableReviewCount = projectReviewCount + findingsCount + healthCount;
  const total = unreadReplyCount + actionableReviewCount;

  const rows: ActionInboxRow[] = [];
  if (unreadReplyCount > 0) {
    rows.push({
      kind: "replies",
      title: "Unread replies",
      detail: `${plural(unreadRows.length, "session")} with agent replies`,
      count: unreadReplyCount,
      tone: "warning",
    });
  }
  if (projectReviewCount > 0) {
    const first = projectReviewItems[0];
    rows.push({
      kind: "project_reviews",
      title: "Project reviews",
      detail: first ? `${first.project_name} - ${first.next_action || first.summary_line || "Review run evidence"}` : "Runs need operator review",
      count: projectReviewCount,
      href: first?.links?.run_url || first?.links?.project_runs_url || "/admin/projects",
      tone: "info",
    });
  }
  if (findingsCount > 0) {
    rows.push({
      kind: "findings",
      title: "Mission Control findings",
      detail: `${plural(findingItems.length, "review finding")} - ${plural(briefCounts?.autofix ?? 0, "repair request")}`,
      count: findingsCount,
      href: "/hub/attention?mode=review",
      tone: "info",
    });
  }
  if (healthCount > 0) {
    rows.push({
      kind: "health",
      title: "Health findings",
      detail: criticalHealth ? `${plural(criticalHealth, "critical")} - ${plural(errorHealth, "error")}` : `${plural(errorHealth, "error")} in latest rollup`,
      count: healthCount,
      href: "/hub/daily-health",
      tone: criticalHealth ? "danger" : "warning",
    });
  }

  if (rows.length === 0) {
    rows.push({
      kind: "replies",
      title: "Caught up",
      detail: "No unread replies or review-ready work.",
      count: 0,
      tone: "success",
    });
  }

  return {
    total,
    unreadReplyCount,
    actionableReviewCount,
    projectReviewCount,
    findingsCount,
    healthCount,
    rows,
    projectReviewItems,
    findingItems,
  };
}
