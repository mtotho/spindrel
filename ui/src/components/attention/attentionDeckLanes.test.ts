import assert from "node:assert/strict";
import test from "node:test";

import {
  getBotReport,
  getIssueIntake,
  getIssueTriage,
  isIssueCandidate,
  modeItems,
  sortDeckItems,
} from "./attentionDeckLanes.js";
import type { AttentionBuckets } from "../spatial-canvas/SpatialAttentionModel.js";
import type { WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention.js";

type ItemSpec = {
  id: string;
  severity?: WorkspaceAttentionItem["severity"];
  evidence?: WorkspaceAttentionItem["evidence"];
  last_seen_at?: string;
};

function fakeItem(spec: ItemSpec): WorkspaceAttentionItem {
  return {
    id: spec.id,
    target_kind: "channel",
    target_id: "ch-1",
    title: `item ${spec.id}`,
    message: "",
    severity: spec.severity ?? "warning",
    status: "open",
    source_type: "bot",
    source_id: "bot-1",
    channel_id: "ch-1",
    channel_name: "test",
    first_seen_at: spec.last_seen_at ?? "2026-01-01T00:00:00Z",
    last_seen_at: spec.last_seen_at ?? "2026-01-01T00:00:00Z",
    occurrence_count: 1,
    assigned_bot_id: null,
    assignment_mode: null,
    assignment_instructions: null,
    evidence: spec.evidence ?? null,
  } as unknown as WorkspaceAttentionItem;
}

function emptyBuckets(): AttentionBuckets {
  return { review: [], triage: [], untriaged: [], assigned: [], processed: [], closed: [] };
}

test("getIssueIntake / getBotReport / getIssueTriage extract evidence sub-objects", () => {
  const intake = fakeItem({ id: "a", evidence: { issue_intake: { kind: "conversation" } } as never });
  const report = fakeItem({ id: "b", evidence: { report_issue: { category: "code_bug" } } as never });
  const triage = fakeItem({ id: "c", evidence: { issue_triage: { state: "packed" } } as never });
  assert.ok(getIssueIntake(intake));
  assert.equal(getIssueIntake(report), null);
  assert.ok(getBotReport(report));
  assert.equal(getBotReport(intake), null);
  assert.ok(getIssueTriage(triage));
});

test("isIssueCandidate accepts intake or report unless triage state is terminal", () => {
  const intake = fakeItem({ id: "a", evidence: { issue_intake: { kind: "conversation" } } as never });
  const report = fakeItem({ id: "b", evidence: { report_issue: { category: "code_bug" } } as never });
  const packed = fakeItem({
    id: "c",
    evidence: { issue_intake: {}, issue_triage: { state: "packed" } } as never,
  });
  const dismissed = fakeItem({
    id: "d",
    evidence: { report_issue: {}, issue_triage: { state: "dismissed" } } as never,
  });
  const needsInfo = fakeItem({
    id: "e",
    evidence: { issue_intake: {}, issue_triage: { state: "needs_info" } } as never,
  });
  const blank = fakeItem({ id: "f" });
  assert.equal(isIssueCandidate(intake), true);
  assert.equal(isIssueCandidate(report), true);
  assert.equal(isIssueCandidate(packed), false);
  assert.equal(isIssueCandidate(dismissed), false);
  assert.equal(isIssueCandidate(needsInfo), false);
  assert.equal(isIssueCandidate(blank), false);
});

test("modeItems('issues') returns the supplied issue candidates instead of an empty list", () => {
  const buckets = emptyBuckets();
  const intake = fakeItem({ id: "intake", evidence: { issue_intake: {} } as never });
  const report = fakeItem({ id: "report", evidence: { report_issue: {} } as never });
  buckets.review.push(report);
  buckets.untriaged.push(intake);

  const issuesLane = modeItems("issues", buckets, [intake, report]);
  assert.deepEqual(
    issuesLane.map((item) => item.id),
    ["intake", "report"],
  );

  const reviewLane = modeItems("review", buckets, [intake, report]);
  assert.deepEqual(reviewLane.map((item) => item.id), ["report"]);

  const inboxLane = modeItems("inbox", buckets, [intake, report]);
  assert.deepEqual(inboxLane.map((item) => item.id), ["intake"]);
});

test("sortDeckItems('issues') prioritizes bot-published conversation issues over agent reports", () => {
  const olderIntake = fakeItem({
    id: "old-intake",
    evidence: { issue_intake: {} } as never,
    last_seen_at: "2026-01-01T00:00:00Z",
  });
  const newerReport = fakeItem({
    id: "new-report",
    evidence: { report_issue: {} } as never,
    last_seen_at: "2026-04-01T00:00:00Z",
  });
  const newerIntake = fakeItem({
    id: "new-intake",
    evidence: { issue_intake: {} } as never,
    last_seen_at: "2026-03-01T00:00:00Z",
  });
  const sorted = sortDeckItems("issues", [newerReport, olderIntake, newerIntake]);
  assert.deepEqual(
    sorted.map((item) => item.id),
    ["new-intake", "old-intake", "new-report"],
  );
});

test("sortDeckItems('review') keeps existing bot-report grouping behaviour", () => {
  const finding = fakeItem({ id: "finding", severity: "error" });
  const botReport = fakeItem({
    id: "bot",
    severity: "error",
    evidence: { report_issue: {} } as never,
  });
  const sorted = sortDeckItems("review", [botReport, finding]);
  assert.deepEqual(sorted.map((item) => item.id), ["finding", "bot"]);
});

test("modeItems('cleared') and ('inbox') compose the right buckets", () => {
  const buckets = emptyBuckets();
  buckets.processed.push(fakeItem({ id: "p1" }));
  buckets.closed.push(fakeItem({ id: "c1" }));
  buckets.untriaged.push(fakeItem({ id: "u1" }));
  buckets.assigned.push(fakeItem({ id: "a1" }));
  assert.deepEqual(modeItems("cleared", buckets, []).map((item) => item.id), ["p1", "c1"]);
  assert.deepEqual(modeItems("inbox", buckets, []).map((item) => item.id), ["u1", "a1"]);
});
