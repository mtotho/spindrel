import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const SOURCE = resolve(process.cwd(), "src/components/attention/AttentionCommandDeck.tsx");

test("selected attention items sync deck lane without rewriting URL mode", () => {
  const source = readFileSync(SOURCE, "utf8");

  assert.match(source, /const setDeckMode = \(next: DeckMode, notify = true\)/);
  assert.match(source, /if \(notify\) onModeChange\?\.\(next\)/);
  assert.match(source, /setDeckMode\("review", false\)/);
  assert.match(source, /setDeckMode\("cleared", false\)/);
  assert.match(source, /setDeckMode\("runs", false\)/);
  assert.match(source, /setDeckMode\("issues", false\)/);
  assert.match(source, /setDeckMode\("inbox", false\)/);
});
