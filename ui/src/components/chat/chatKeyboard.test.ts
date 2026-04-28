import test from "node:test";
import assert from "node:assert/strict";

import { isEditableKeyboardTarget } from "./chatKeyboard.js";

test("editable keyboard guard catches form controls", () => {
  assert.equal(isEditableKeyboardTarget({ tagName: "input" }), true);
  assert.equal(isEditableKeyboardTarget({ tagName: "TEXTAREA" }), true);
  assert.equal(isEditableKeyboardTarget({ tagName: "select" }), true);
});

test("editable keyboard guard catches contenteditable and textbox ancestors", () => {
  assert.equal(isEditableKeyboardTarget({ isContentEditable: true }), true);
  assert.equal(isEditableKeyboardTarget({ closest: () => ({}) }), true);
});

test("editable keyboard guard allows normal page targets", () => {
  assert.equal(isEditableKeyboardTarget(null), false);
  assert.equal(isEditableKeyboardTarget({ tagName: "DIV", closest: () => null }), false);
});
