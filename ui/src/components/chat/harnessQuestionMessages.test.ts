import test from "node:test";
import assert from "node:assert/strict";

import type { Message } from "../../types/api.js";
import {
  isHarnessQuestionTransportMessage,
  isPendingHarnessQuestionMessage,
  pendingHarnessQuestionTurnIds,
} from "./harnessQuestionMessages.js";

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: "message-1",
    session_id: "session-1",
    role: "assistant",
    content: "",
    created_at: "2026-04-27T18:00:00.000Z",
    metadata: {},
    ...overrides,
  };
}

test("harness question answer transport rows are hidden from transcript lists", () => {
  assert.equal(
    isHarnessQuestionTransportMessage(makeMessage({
      role: "user",
      metadata: { source: "harness_question", harness_question_id: "question-1" },
    })),
    true,
  );
  assert.equal(
    isHarnessQuestionTransportMessage(makeMessage({
      role: "user",
      metadata: { hidden: true },
    })),
    true,
  );
});

test("pending harness question helpers track only active question turns", () => {
  const pending = makeMessage({
    id: "question-1",
    correlation_id: "turn-1",
    metadata: {
      kind: "harness_question",
      harness_interaction: { status: "pending" },
    },
  });
  const answered = makeMessage({
    id: "question-2",
    correlation_id: "turn-2",
    metadata: {
      kind: "harness_question",
      harness_interaction: { status: "submitted" },
    },
  });

  assert.equal(isPendingHarnessQuestionMessage(pending, { sessionId: "session-1" }), true);
  assert.equal(isPendingHarnessQuestionMessage(answered, { sessionId: "session-1" }), false);
  assert.deepEqual([...pendingHarnessQuestionTurnIds([pending, answered])], ["turn-1"]);
});
