import {
  getOperatorTriage,
  isActiveAttentionItem,
  isOperatorTriageProcessed,
  isOperatorTriageReadyForReview,
  isOperatorTriageRunning,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";

export const OPERATOR_BOT_ID = "orchestrator";

export type AttentionWorkflowState =
  | "operator_review"
  | "in_sweep"
  | "processed"
  | "closed"
  | "assigned"
  | "untriaged";

export type AttentionLaneKey =
  | "review"
  | "triage"
  | "untriaged"
  | "assigned"
  | "processed"
  | "closed";

export type AttentionBuckets = Record<AttentionLaneKey, WorkspaceAttentionItem[]>;

export const severityRank: Record<string, number> = { info: 0, warning: 1, error: 2, critical: 3 };

export function getAttentionWorkflowState(item: WorkspaceAttentionItem): AttentionWorkflowState {
  if (isOperatorTriageRunning(item)) return "in_sweep";
  if (isOperatorTriageReadyForReview(item)) return "operator_review";
  if (isOperatorTriageProcessed(item)) return "processed";
  if (item.status === "resolved" || item.status === "acknowledged") return "closed";
  if (item.assigned_bot_id) return "assigned";
  return "untriaged";
}

export function isAttentionStillActionable(item: WorkspaceAttentionItem): boolean {
  const state = getAttentionWorkflowState(item);
  return state === "operator_review" || state === "in_sweep" || state === "assigned" || state === "untriaged";
}

export function isAttentionSweepCandidate(item: WorkspaceAttentionItem): boolean {
  const state = getAttentionWorkflowState(item);
  return isActiveAttentionItem(item) && (state === "assigned" || state === "untriaged");
}

export function activeAttentionItems(items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  return items.filter(isAttentionStillActionable);
}

export function sweepCandidateItems(items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  return items.filter(isAttentionSweepCandidate);
}

export function attentionLaneFor(item: WorkspaceAttentionItem): AttentionLaneKey {
  const state = getAttentionWorkflowState(item);
  if (state === "operator_review") return "review";
  if (state === "in_sweep") return "triage";
  if (state === "processed") return "processed";
  if (state === "closed") return "closed";
  if (state === "assigned") return "assigned";
  return "untriaged";
}

export function bucketAttentionItems(items: WorkspaceAttentionItem[]): AttentionBuckets {
  const buckets: AttentionBuckets = {
    review: [],
    triage: [],
    untriaged: [],
    assigned: [],
    processed: [],
    closed: [],
  };
  for (const item of items) buckets[attentionLaneFor(item)].push(item);
  for (const bucket of Object.values(buckets)) {
    bucket.sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
  }
  return buckets;
}

export function attentionBucketSummary(buckets: AttentionBuckets): string {
  const review = buckets.review.length;
  const untriaged = buckets.untriaged.length + buckets.assigned.length;
  const running = buckets.triage.length;
  const cleared = buckets.processed.length;
  const parts = [
    `${review} review`,
    `${untriaged} untriaged`,
    running ? `${running} running` : null,
    `${cleared} cleared`,
  ].filter(Boolean);
  return parts.join(" · ");
}

export function attentionItemTriageLabel(item: WorkspaceAttentionItem): string {
  const state = getAttentionWorkflowState(item);
  if (state === "operator_review") return "operator review";
  if (state === "in_sweep") return "operator running";
  if (state === "processed") return "cleared by operator";
  if (state === "closed") return item.status;
  if (state === "assigned") return "assigned";
  return "untriaged";
}

export function attentionMapCueLabel(item: WorkspaceAttentionItem): string {
  const triage = getOperatorTriage(item);
  if (getAttentionWorkflowState(item) === "operator_review") {
    return triage?.classification ? `Operator reviewed: ${triage.classification.replaceAll("_", " ")}` : "Operator reviewed";
  }
  return item.title;
}
