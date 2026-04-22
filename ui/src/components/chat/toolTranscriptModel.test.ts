import test from "node:test";
import assert from "node:assert/strict";

import {
  buildOrderedTurnBodyItemsFromLive,
  buildOrderedTurnBodyItemsFromPersisted,
} from "./toolTranscriptModel.js";

test("persisted ordered turn body keeps transcript order and canonical surfaces", () => {
  const items = buildOrderedTurnBodyItemsFromPersisted({
    transcriptEntries: [
      { id: "text-1", kind: "text", text: "Before edit.\n" },
      { id: "tool-1", kind: "tool_call", toolCallId: "call-edit" },
      { id: "text-2", kind: "text", text: "Between edits.\n" },
      { id: "tool-2", kind: "tool_call", toolCallId: "call-widget" },
    ],
    toolCalls: [
      {
        id: "call-edit",
        name: "file",
        arguments: JSON.stringify({ operation: "edit", path: "notes.md" }),
        surface: "transcript",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited notes.md",
          path: "notes.md",
          diff_stats: { additions: 1, deletions: 1 },
        },
      },
      {
        id: "call-widget",
        name: "emit_widget",
        arguments: "{}",
        surface: "widget",
        summary: {
          kind: "result",
          subject_type: "widget",
          label: "Widget available",
          target_label: "Clock",
        },
      },
    ],
    toolResults: [
      {
        content_type: "application/vnd.spindrel.diff+text",
        body: "@@ -1 +1 @@\n-old\n+new",
        plain_body: "Edited notes.md",
        display: "inline",
        truncated: false,
        record_id: "result-edit",
        byte_size: 24,
      },
      {
        content_type: "application/vnd.spindrel.components+json",
        body: { component: "Clock" },
        plain_body: "Clock",
        display: "inline",
        truncated: false,
        record_id: "result-widget",
        byte_size: 32,
        display_label: "Clock",
      },
    ],
  });

  assert.deepEqual(
    items.map((item) => item.kind),
    ["text", "transcript", "text", "widget"],
  );
  assert.equal(items[1]?.kind, "transcript");
  assert.equal(items[3]?.kind, "widget");
  if (items[1]?.kind !== "transcript") throw new Error("expected transcript item");
  assert.equal(items[1].entries[0]?.detailKind, "inline-diff");
});

test("live and persisted ordered turn body builders agree on item kinds", () => {
  const transcriptEntries = [
    { id: "text-1", kind: "text" as const, text: "Before edit.\n" },
    { id: "tool-1", kind: "tool_call" as const, toolCallId: "call-edit" },
    { id: "text-2", kind: "text" as const, text: "After edit.\n" },
  ];

  const persisted = buildOrderedTurnBodyItemsFromPersisted({
    transcriptEntries,
    toolCalls: [
      {
        id: "call-edit",
        name: "file",
        arguments: JSON.stringify({ operation: "edit", path: "notes.md" }),
        surface: "transcript",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited notes.md",
          path: "notes.md",
          diff_stats: { additions: 1, deletions: 1 },
        },
      },
    ],
    toolResults: [
      {
        content_type: "application/vnd.spindrel.diff+text",
        body: "@@ -1 +1 @@\n-old\n+new",
        plain_body: "Edited notes.md",
        display: "inline",
        truncated: false,
        record_id: "result-edit",
        byte_size: 24,
      },
    ],
  });

  const live = buildOrderedTurnBodyItemsFromLive({
    transcriptEntries,
    toolCalls: [
      {
        id: "call-edit",
        name: "file",
        args: JSON.stringify({ operation: "edit", path: "notes.md" }),
        surface: "transcript",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited notes.md",
          path: "notes.md",
          diff_stats: { additions: 1, deletions: 1 },
        },
        status: "done",
        envelope: {
          content_type: "application/vnd.spindrel.diff+text",
          body: "@@ -1 +1 @@\n-old\n+new",
          plain_body: "Edited notes.md",
          display: "inline",
          truncated: false,
          record_id: "result-edit",
          byte_size: 24,
        },
      },
    ],
  });

  assert.deepEqual(
    live.map((item) => item.kind),
    persisted.map((item) => item.kind),
  );
});

test("persisted ordered turn body throws when a transcript tool entry has no canonical tool call", () => {
  const items = buildOrderedTurnBodyItemsFromPersisted({
    transcriptEntries: [
      { id: "tool-1", kind: "tool_call", toolCallId: "missing-call" },
    ],
    toolCalls: [],
    toolResults: [],
  });

  assert.deepEqual(items.map((item) => item.kind), ["transcript"]);
  if (items[0]?.kind !== "transcript") throw new Error("expected transcript placeholder item");
  assert.equal(items[0].entries[0]?.label, "Missing tool data");
});

test("strict mode still throws when a transcript tool entry has no canonical tool call", () => {
  assert.throws(() =>
    buildOrderedTurnBodyItemsFromPersisted({
      transcriptEntries: [
        { id: "tool-1", kind: "tool_call", toolCallId: "missing-call" },
      ],
      toolCalls: [],
      toolResults: [],
      missingToolBehavior: "throw",
    }),
  );
});
