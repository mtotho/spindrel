import type { WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention.js";
import type { AttentionBuckets } from "../spatial-canvas/SpatialAttentionModel.js";
import type { AttentionDeckMode } from "../../lib/hubRoutes.js";

// Inlined to keep this module self-contained and runtime-import-free for node tests.
const severityRank: Record<string, number> = { info: 0, warning: 1, error: 2, critical: 3 };

// These helpers traverse loosely-typed evidence payloads. Callers narrow as needed.
export function getBotReport(item: WorkspaceAttentionItem): any | null {
  const report = item.evidence?.report_issue;
  return report && typeof report === "object" ? report : null;
}

export function getIssueIntake(item: WorkspaceAttentionItem): any | null {
  const intake = item.evidence?.issue_intake;
  return intake && typeof intake === "object" ? intake : null;
}

export function getIssueTriage(item: WorkspaceAttentionItem): any | null {
  const triage = item.evidence?.issue_triage;
  return triage && typeof triage === "object" ? triage : null;
}

export function isIssueCandidate(item: WorkspaceAttentionItem): boolean {
  if (!getIssueIntake(item) && !getBotReport(item)) return false;
  const state = String(getIssueTriage(item)?.state ?? "");
  return !["packed", "dismissed", "needs_info"].includes(state);
}

export function sortAttention(items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  return [...items].sort((a, b) => {
    const severity = severityRank[b.severity] - severityRank[a.severity];
    if (severity !== 0) return severity;
    return (
      new Date(b.last_seen_at ?? b.first_seen_at ?? 0).getTime() -
      new Date(a.last_seen_at ?? a.first_seen_at ?? 0).getTime()
    );
  });
}

export function modeItems(
  mode: AttentionDeckMode,
  buckets: AttentionBuckets,
  issueCandidates: WorkspaceAttentionItem[],
): WorkspaceAttentionItem[] {
  if (mode === "review") return buckets.review;
  if (mode === "issues") return issueCandidates;
  if (mode === "inbox") return [...buckets.untriaged, ...buckets.assigned];
  if (mode === "cleared") return [...buckets.processed, ...buckets.closed];
  return [...buckets.triage, ...buckets.review];
}

export function sortDeckItems(
  mode: AttentionDeckMode,
  items: WorkspaceAttentionItem[],
): WorkspaceAttentionItem[] {
  const sorted = sortAttention(items);
  if (mode === "review") {
    return sorted.sort(
      (a, b) => Number(Boolean(getBotReport(a))) - Number(Boolean(getBotReport(b))),
    );
  }
  if (mode === "issues") {
    // Bot-published conversation issues (issue_intake evidence) come first, so
    // operators can sweep them before falling back to autonomous agent reports.
    return sorted.sort(
      (a, b) => Number(Boolean(getIssueIntake(b))) - Number(Boolean(getIssueIntake(a))),
    );
  }
  return sorted;
}
