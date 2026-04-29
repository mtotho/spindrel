import test from "node:test";
import assert from "node:assert/strict";

import { parsePlanPayload } from "./planPayload.js";

const plan = {
  title: "Native Spindrel Answered Plan",
  status: "draft",
  revision: 1,
  session_id: "session-1",
  task_slug: "native-spindrel-answered-plan",
  summary: "Verify answer handoff",
  scope: "Live E2E diagnostics only",
  assumptions: [],
  open_questions: [],
  steps: [{ id: "step-1", label: "Read submitted plan answers", status: "pending" }],
  artifacts: [],
  acceptance_criteria: ["Answer handoff is visible"],
  outcome: "",
  mode: "planning",
};

test("plan payload parser accepts inline plan bodies", () => {
  assert.equal(parsePlanPayload(JSON.stringify(plan))?.title, "Native Spindrel Answered Plan");
  assert.equal(parsePlanPayload(plan)?.steps[0]?.label, "Read submitted plan answers");
});

test("plan payload parser unwraps fetched out-of-line tool results", () => {
  const fetchedToolResult = JSON.stringify({
    _envelope: {
      content_type: "application/vnd.spindrel.plan+json",
      body: JSON.stringify(plan),
      truncated: false,
    },
    llm: "gpt-5.4-mini",
    plan,
  });

  const parsed = parsePlanPayload(fetchedToolResult);
  assert.equal(parsed?.revision, 1);
  assert.equal(parsed?.steps[0]?.label, "Read submitted plan answers");
});

test("plan payload parser falls back to top-level plan field when envelope body is absent", () => {
  const fetchedToolResult = JSON.stringify({
    _envelope: {
      content_type: "application/vnd.spindrel.plan+json",
      body: null,
      truncated: true,
    },
    plan,
  });

  assert.equal(parsePlanPayload(fetchedToolResult)?.summary, "Verify answer handoff");
});
