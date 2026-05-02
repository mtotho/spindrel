import test from "node:test";
import assert from "node:assert/strict";

import { buildActionInboxModel, type ActionInboxInput } from "./actionInbox.ts";
import type { WorkspaceAttentionItem } from "../api/hooks/useWorkspaceAttention";
import type { SessionReadState } from "../api/hooks/useUnread";
import type { ProjectFactoryReviewInboxItem } from "../types/api";

function unread(count: number): SessionReadState {
  return {
    user_id: "user",
    session_id: `session-${count}`,
    channel_id: "channel-1",
    last_read_message_id: null,
    last_read_at: null,
    first_unread_at: "2026-05-01T10:00:00Z",
    latest_unread_at: "2026-05-01T10:00:00Z",
    latest_unread_message_id: null,
    latest_unread_correlation_id: null,
    unread_agent_reply_count: count,
    reminder_due_at: null,
    reminder_sent_at: null,
  };
}

function attention(overrides: Partial<WorkspaceAttentionItem>): WorkspaceAttentionItem {
  return {
    id: overrides.id ?? "attention-1",
    source_type: overrides.source_type ?? "bot",
    source_id: "bot-1",
    channel_id: "channel-1",
    target_kind: "channel",
    target_id: "channel-1",
    dedupe_key: "key",
    severity: "warning",
    title: "Finding",
    message: "Needs review",
    next_steps: [],
    requires_response: false,
    status: "open",
    occurrence_count: 1,
    evidence: {},
    ...overrides,
  };
}

function projectItem(overrides: Partial<ProjectFactoryReviewInboxItem> = {}): ProjectFactoryReviewInboxItem {
  return {
    id: "run-1",
    project_id: "project-1",
    project_name: "Project",
    task_id: "task-1",
    title: "Run",
    state: "ready_for_review",
    links: { run_url: "/admin/projects/project-1/runs/task-1" },
    ...overrides,
  };
}

test("action inbox excludes raw untriaged attention from the actionable count", () => {
  const model = buildActionInboxModel({
    attentionItems: [attention({ evidence: {}, title: "Raw signal" })],
  });

  assert.equal(model.total, 0);
  assert.equal(model.findingsCount, 0);
  assert.equal(model.rows[0]?.title, "Caught up");
});

test("action inbox counts replies, project reviews, findings, and health", () => {
  const input: ActionInboxInput = {
    unreadStates: [unread(2)],
    projectReviewInbox: {
      summary: { needs_attention_count: 1 },
      items: [projectItem()],
      projects: [],
    },
    attentionItems: [
      attention({ id: "finding", evidence: { operator_triage: { state: "ready_for_review" } } }),
    ],
    attentionBrief: {
      generated_at: "2026-05-01T10:00:00Z",
      summary: { autofix: 1, blockers: 0, fix_packs: 0, decisions: 0, quiet: 0, running: 0, cleared: 0, total: 1 },
      next_action: { kind: "empty", title: "", description: "" },
      blockers: [],
      fix_packs: [],
      decisions: [],
      autofix_queue: [],
      quiet_digest: { count: 0, groups: [] },
      running: [],
      cleared: [],
    },
    health: { summary: { error_count: 1, critical_count: 1 } },
  };
  const model = buildActionInboxModel(input);

  assert.equal(model.unreadReplyCount, 2);
  assert.equal(model.projectReviewCount, 1);
  assert.equal(model.findingsCount, 2);
  assert.equal(model.healthCount, 2);
  assert.equal(model.total, 7);
  assert.deepEqual(model.rows.map((row) => row.kind), ["replies", "project_reviews", "findings", "health"]);
});

test("action inbox does not treat reviewed project runs as actionable when summary is absent", () => {
  const model = buildActionInboxModel({
    projectReviewInbox: {
      summary: {},
      items: [projectItem({ state: "reviewed" }), projectItem({ id: "run-2", state: "reviewing" })],
      projects: [],
    },
  });

  assert.equal(model.projectReviewCount, 0);
  assert.equal(model.total, 0);
});
