import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  collapseProjectRunReceiptsForReview,
  projectRunReceiptReviewKey,
} from "./projectRunReceipts.ts";
import type { ProjectRunReceipt } from "../types/api";

let receiptCounter = 0;

function receipt(overrides: Partial<ProjectRunReceipt>): ProjectRunReceipt {
  receiptCounter += 1;
  return {
    id: overrides.id ?? `receipt-${receiptCounter}`,
    project_id: "project-1",
    status: "completed",
    summary: "Done",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("project run receipt review grouping", () => {
  it("prefers the persisted idempotency key", () => {
    assert.equal(
      projectRunReceiptReviewKey(receipt({ idempotency_key: "task:123", task_id: "other" })),
      "idempotency:task:123",
    );
  });

  it("collapses duplicate handoff receipts while keeping newest-first order", () => {
    const rows = collapseProjectRunReceiptsForReview([
      receipt({ id: "new", handoff_url: "https://example.invalid/pr/1", summary: "new" }),
      receipt({ id: "older", handoff_url: "https://example.invalid/pr/1", summary: "older" }),
      receipt({ id: "separate", handoff_url: "https://example.invalid/pr/2", summary: "separate" }),
    ]);

    assert.deepEqual(rows.map((row) => row.id), ["new", "separate"]);
    assert.equal(rows[0]?.duplicate_count, 2);
    assert.equal(rows[1]?.duplicate_count, 1);
  });
});
