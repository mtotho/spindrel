import assert from "node:assert/strict";
import {
  classifyWhen,
  describeWhen,
  buildEdges,
  staleWhenStepRefs,
} from "./edges.js";

// classifyWhen ---------------------------------------------------------------

assert.equal(classifyWhen(null), "unconditional");
assert.equal(classifyWhen({}), "unconditional");
assert.equal(classifyWhen({ step: "s1", status: "done" }), "simple");
assert.equal(classifyWhen({ step: "s1", output_contains: "x" }), "simple");
assert.equal(classifyWhen({ step: "s1", output_not_contains: "y" }), "simple");

assert.equal(classifyWhen({ all: [{ step: "s1", status: "done" }] }), "complex");
assert.equal(classifyWhen({ any: [{ step: "s1" }] }), "complex");
assert.equal(classifyWhen({ not: { param: "x" } }), "complex");
assert.equal(classifyWhen({ param: "x", equals: 1 }), "complex");
assert.equal(classifyWhen({ step: "s1", weird: true }), "complex"); // unrecognized key

// describeWhen ---------------------------------------------------------------

assert.equal(describeWhen(null), null);
assert.equal(describeWhen({}), null);
assert.equal(describeWhen({ step: "s1", status: "done" }), "if status = done");
assert.equal(describeWhen({ step: "s1", output_contains: "urgent" }), 'if contains "urgent"');
assert.equal(describeWhen({ step: "s1", output_not_contains: "error" }), 'if NOT contains "error"');
assert.equal(describeWhen({ all: [{ step: "x", status: "done" }] }), null); // complex → no label

// buildEdges -----------------------------------------------------------------

{
  // Sequential primary edges, no when
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const },
    { id: "c", type: "agent" as const, on_failure: "abort" as const },
  ];
  const edges = buildEdges(steps);
  assert.equal(edges.length, 2);
  assert.equal(edges[0].fromId, "a");
  assert.equal(edges[0].toId, "b");
  assert.equal(edges[0].kind, "unconditional");
  assert.equal(edges[0].isSecondary, false);
}

{
  // Simple condition → labeled primary edge
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "a", output_contains: "go" } },
  ];
  const edges = buildEdges(steps);
  assert.equal(edges.length, 1);
  assert.equal(edges[0].kind, "simple");
  assert.equal(edges[0].label, 'if contains "go"');
}

{
  // Complex condition → primary edge but no label
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const,
      when: { all: [{ step: "a", status: "done" }, { not: { param: "skip" } }] } },
  ];
  const edges = buildEdges(steps);
  assert.equal(edges[0].kind, "complex");
  assert.equal(edges[0].label, null);
  // when object preserved verbatim
  assert.deepEqual(edges[0].when, steps[1].when);
}

{
  // Secondary edge: when.step references a non-immediate predecessor
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const },
    { id: "c", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "a", status: "done" } }, // a is non-immediate predecessor
  ];
  const edges = buildEdges(steps);
  // Primary a->b (unconditional), primary b->c (simple, references a),
  // secondary a->c (because when.step references non-immediate).
  assert.equal(edges.length, 3);
  const primary = edges.filter((e) => !e.isSecondary);
  const secondary = edges.filter((e) => e.isSecondary);
  assert.equal(primary.length, 2);
  assert.equal(secondary.length, 1);
  assert.equal(secondary[0].fromId, "a");
  assert.equal(secondary[0].toId, "c");
}

{
  // when.step references the immediate predecessor → no secondary edge
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "a", status: "done" } },
  ];
  const edges = buildEdges(steps);
  assert.equal(edges.length, 1);
  assert.equal(edges[0].isSecondary, false);
}

// staleWhenStepRefs ----------------------------------------------------------

{
  // Forward reference (target index >= current) → stale
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "b", status: "done" } },  // forward ref
    { id: "b", type: "agent" as const, on_failure: "abort" as const },
  ];
  const stale = staleWhenStepRefs(steps);
  assert.equal(stale.has("a"), true);
  assert.equal(stale.has("b"), false);
}

{
  // Reference to missing step → stale
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "ghost", status: "done" } },
  ];
  const stale = staleWhenStepRefs(steps);
  assert.equal(stale.has("b"), true);
}

{
  // Valid backward reference → not stale
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const,
      when: { step: "a", status: "done" } },
  ];
  const stale = staleWhenStepRefs(steps);
  assert.equal(stale.size, 0);
}

console.log("edges.test.ts passed");
