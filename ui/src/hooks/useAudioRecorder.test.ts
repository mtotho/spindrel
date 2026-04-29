import test from "node:test";
import assert from "node:assert/strict";
import { mimeToFormat } from "./audioRecorderFormat.js";

test("audio recorder maps browser webm opus MIME to webm format", () => {
  assert.equal(mimeToFormat("audio/webm;codecs=opus"), "webm");
});

test("audio recorder keeps mp4 format for Safari recordings", () => {
  assert.equal(mimeToFormat("audio/mp4"), "mp4");
});

test("audio recorder defaults empty MIME to webm", () => {
  assert.equal(mimeToFormat(""), "webm");
});
