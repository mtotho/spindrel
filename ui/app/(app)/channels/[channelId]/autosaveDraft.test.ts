import assert from "node:assert/strict";
import { test } from "node:test";

import { saveMatchesCurrentDraft, shouldApplyServerDraft } from "./autosaveDraft.ts";

test("autosave server hydration does not overwrite dirty local textarea edits", () => {
  assert.equal(
    shouldApplyServerDraft({ dirty: true, pending: false, hasScheduledSave: false }),
    false,
  );
});

test("autosave server hydration waits while a save is pending or scheduled", () => {
  assert.equal(
    shouldApplyServerDraft({ dirty: false, pending: true, hasScheduledSave: false }),
    false,
  );
  assert.equal(
    shouldApplyServerDraft({ dirty: false, pending: false, hasScheduledSave: true }),
    false,
  );
});

test("autosave can rehydrate only when the local draft is stable", () => {
  assert.equal(
    shouldApplyServerDraft({ dirty: false, pending: false, hasScheduledSave: false }),
    true,
  );
});

test("completed save is clean only if it still matches the current draft", () => {
  assert.equal(
    saveMatchesCurrentDraft({
      savedDraft: { prompt: "saved text" },
      currentDraft: { prompt: "saved text plus more typing" },
    }),
    false,
  );
  assert.equal(
    saveMatchesCurrentDraft({
      savedDraft: { prompt: "saved text" },
      currentDraft: { prompt: "saved text" },
    }),
    true,
  );
});
