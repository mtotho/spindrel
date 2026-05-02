import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("./index.tsx", import.meta.url), "utf8");

test("provider model form uses canonical input theme tokens", () => {
  assert.doesNotMatch(source, /bg-input-bg/);
  assert.match(source, /border-input-border/);
  assert.match(source, /bg-input/);
  assert.match(source, /placeholder:text-text-dim/);
});
