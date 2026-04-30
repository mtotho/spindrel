import test from "node:test";
import assert from "node:assert/strict";
import {
  WORKSPACE_ATTENTION_BRIEF_KEY,
  getToolErrorReviewSignal,
  reconcileAttentionItems,
  type WorkspaceAttentionItem,
} from "./useWorkspaceAttention.js";

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

test("workspace attention brief has a stable cache key", () => {
  assert.deepEqual(WORKSPACE_ATTENTION_BRIEF_KEY, ["workspace-attention-brief"]);
});

test("workspace attention brief exposes agent readiness autofix queue types", async () => {
  const source = await import("node:fs").then(({ readFileSync }) => readFileSync(new URL("./useWorkspaceAttention.ts", import.meta.url), "utf8"));

  assert.match(source, /interface AgentReadinessAutofixItem/);
  assert.match(source, /autofix: number/);
  assert.match(source, /autofix_queue: AgentReadinessAutofixItem\[\]/);
  assert.match(source, /receipt: ExecutionReceipt/);
});

test("getToolErrorReviewSignal labels retryable tool-call evidence", () => {
  const signal = getToolErrorReviewSignal(item({
    evidence: {
      kind: "tool_call",
      classification: "retryable_contract",
      error_code: "http_429",
      error_kind: "rate_limited",
      retryable: true,
      fallback: "Wait and retry with backoff.",
    },
  }));

  assert.deepEqual(signal, {
    label: "Retryable",
    tone: "warning",
    nextAction: "Wait and retry with backoff.",
    errorCode: "http_429",
    errorKind: "rate_limited",
    retryable: true,
  });
});

test("getToolErrorReviewSignal labels repeated benign tool-call evidence", () => {
  const signal = getToolErrorReviewSignal(item({
    evidence: {
      kind: "tool_call",
      classification: "repeated_benign_contract",
      error_code: "invalid_json_body",
      error_kind: "validation",
      retryable: false,
    },
  }));

  assert.equal(signal?.label, "Repeated benign");
  assert.equal(signal?.tone, "warning");
  assert.equal(signal?.retryable, false);
});

test("getToolErrorReviewSignal labels internal tool-call evidence as platform bugs", () => {
  const signal = getToolErrorReviewSignal(item({
    evidence: {
      kind: "tool_call",
      classification: "platform_contract",
      error_code: "tool_error",
      error_kind: "internal",
      retryable: false,
    },
  }));

  assert.equal(signal?.label, "Platform bug");
  assert.equal(signal?.tone, "danger");
});
