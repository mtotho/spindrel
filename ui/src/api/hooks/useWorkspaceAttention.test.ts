import test from "node:test";
import assert from "node:assert/strict";
import { reconcileAttentionItems, type WorkspaceAttentionItem } from "./useWorkspaceAttention.js";

function item(overrides: Partial<WorkspaceAttentionItem> = {}): WorkspaceAttentionItem {
  return {
    id: "attention-1",
    source_type: "bot",
    source_id: "bot-a",
    channel_id: "channel-1",
    channel_name: "Quality Assurance",
    target_kind: "channel",
    target_id: "channel-1",
    target_node_id: "node-1",
    dedupe_key: "bot-a:channel-1:test",
    severity: "warning",
    title: "Needs attention",
    message: "Something happened",
    next_steps: [],
    requires_response: false,
    status: "open",
    occurrence_count: 1,
    evidence: {},
    latest_correlation_id: null,
    response_message_id: null,
    first_seen_at: null,
    last_seen_at: null,
    responded_at: null,
    resolved_at: null,
    ...overrides,
  };
}

test("reconcileAttentionItems updates acknowledged items in cached lists", () => {
  const original = item();
  const updated = item({ status: "acknowledged" });

  assert.deepEqual(reconcileAttentionItems([original], updated), [updated]);
});

test("reconcileAttentionItems removes resolved items from active cached lists", () => {
  const original = item();
  const other = item({ id: "attention-2", title: "Other" });
  const resolved = item({ status: "resolved", resolved_at: "2026-04-26T18:00:00Z" });

  assert.deepEqual(reconcileAttentionItems([original, other], resolved), [other]);
});

test("reconcileAttentionItems removes acknowledged items from active cached lists", () => {
  const original = item();
  const acknowledged = item({ status: "acknowledged" });

  assert.deepEqual(reconcileAttentionItems([original], acknowledged), []);
});
