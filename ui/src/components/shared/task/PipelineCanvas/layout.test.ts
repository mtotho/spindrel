import assert from "node:assert/strict";
import { ensurePositions, setNodePosition, NODE_H, VERTICAL_GAP } from "./layout.js";

// ensurePositions -----------------------------------------------------------

{
  // Empty layout → all steps auto-placed
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const },
  ];
  const result = ensurePositions(steps, {});
  assert.ok(result.nodes);
  assert.ok(result.nodes!.a);
  assert.ok(result.nodes!.b);
  // b stacks below a
  assert.equal(result.nodes!.b.y, result.nodes!.a.y + NODE_H + VERTICAL_GAP);
}

{
  // Existing positions are preserved
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
  ];
  const layout = { version: 1, nodes: { a: { x: 999, y: 999 } } };
  const result = ensurePositions(steps, layout);
  assert.equal(result.nodes!.a.x, 999);
  assert.equal(result.nodes!.a.y, 999);
}

{
  // New step joins existing-positioned steps stacked below them
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
    { id: "b", type: "agent" as const, on_failure: "abort" as const },
  ];
  const layout = { version: 1, nodes: { a: { x: 0, y: 200 } } };
  const result = ensurePositions(steps, layout);
  assert.equal(result.nodes!.a.x, 0);
  assert.equal(result.nodes!.a.y, 200);
  // b auto-places below the existing-most-bottom node
  assert.ok(result.nodes!.b.y > 200 + NODE_H);
}

{
  // Steps removed → their positions get pruned
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
  ];
  const layout = { version: 1, nodes: { a: { x: 0, y: 0 }, gone: { x: 5, y: 5 } } };
  const result = ensurePositions(steps, layout);
  assert.equal(Object.keys(result.nodes!).length, 1);
  assert.ok(result.nodes!.a);
  assert.equal((result.nodes! as any).gone, undefined);
}

{
  // No-op when nothing changes — must return the same reference for cheap memoization
  const steps = [
    { id: "a", type: "agent" as const, on_failure: "abort" as const },
  ];
  const layout = { version: 1, nodes: { a: { x: 0, y: 0 } } };
  const result = ensurePositions(steps, layout);
  assert.equal(result, layout);
}

// setNodePosition -----------------------------------------------------------

{
  const layout = { version: 1, nodes: { a: { x: 0, y: 0 } } };
  const updated = setNodePosition(layout, "a", { x: 50, y: 60 });
  assert.deepEqual(updated.nodes!.a, { x: 50, y: 60 });
  // immutability
  assert.deepEqual(layout.nodes!.a, { x: 0, y: 0 });
}

{
  // Adding a position for a previously unpositioned node
  const layout = { version: 1, nodes: { a: { x: 0, y: 0 } } };
  const updated = setNodePosition(layout, "b", { x: 100, y: 200 });
  assert.deepEqual(updated.nodes!.b, { x: 100, y: 200 });
  // existing positions untouched
  assert.deepEqual(updated.nodes!.a, { x: 0, y: 0 });
}

{
  // Layout without nodes field
  const layout = { version: 1 };
  const updated = setNodePosition(layout, "a", { x: 1, y: 2 });
  assert.deepEqual(updated.nodes!.a, { x: 1, y: 2 });
}

console.log("layout.test.ts passed");
