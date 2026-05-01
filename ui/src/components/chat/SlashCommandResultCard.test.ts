import test from "node:test";
import assert from "node:assert/strict";

import { inlinePreviewValue } from "./slashPreviewValue.js";

test("slash command result inline preview never emits object object", () => {
  assert.equal(inlinePreviewValue({ count: 2 }), "1 field");
  assert.equal(inlinePreviewValue(["a", "b"]), "2 items");
  assert.notEqual(inlinePreviewValue({ count: 2 }), "[object Object]");
});
