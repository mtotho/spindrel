import type { ProjectRunReceipt } from "@/src/types/api";

export type ProjectRunReceiptForReview = ProjectRunReceipt & {
  duplicate_count?: number;
};

export function projectRunReceiptReviewKey(receipt: ProjectRunReceipt): string {
  if (receipt.idempotency_key) return `idempotency:${receipt.idempotency_key}`;
  if (receipt.task_id) return `task:${receipt.task_id}`;
  if (receipt.handoff_url) return `handoff:${receipt.handoff_url}`;
  if (receipt.branch && receipt.base_branch && receipt.commit_sha) {
    return `git:${receipt.base_branch}:${receipt.branch}:${receipt.commit_sha}`;
  }
  if (receipt.session_id && receipt.branch) return `session-branch:${receipt.session_id}:${receipt.branch}`;
  return `receipt:${receipt.id}`;
}

export function collapseProjectRunReceiptsForReview(receipts?: ProjectRunReceipt[]): ProjectRunReceiptForReview[] {
  const collapsed = new Map<string, ProjectRunReceiptForReview>();
  for (const receipt of receipts ?? []) {
    const key = projectRunReceiptReviewKey(receipt);
    const existing = collapsed.get(key);
    if (!existing) {
      collapsed.set(key, { ...receipt, duplicate_count: 1 });
      continue;
    }
    existing.duplicate_count = (existing.duplicate_count ?? 1) + 1;
  }
  return Array.from(collapsed.values());
}
