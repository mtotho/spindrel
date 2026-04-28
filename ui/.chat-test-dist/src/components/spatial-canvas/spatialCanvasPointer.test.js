import test from "node:test";
import assert from "node:assert/strict";
import { isEmptySpaceClickGesture } from "./spatialCanvasPointer.js";
test("empty-space pointer gesture counts as a click inside the drift threshold", () => {
    assert.equal(isEmptySpaceClickGesture({ startX: 100, startY: 200, endX: 102, endY: 203 }), true);
});
test("empty-space pointer gesture does not count as a click after a pan drag", () => {
    assert.equal(isEmptySpaceClickGesture({ startX: 100, startY: 200, endX: 112, endY: 200 }), false);
});
