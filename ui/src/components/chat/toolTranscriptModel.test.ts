import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAssistantTurnBodyItems,
  buildLegacyAssistantTurnBody,
} from "./toolTranscriptModel.js";

test("canonical assistant turn body preserves ordered multi-tool turns", () => {
  const items = buildAssistantTurnBodyItems({
    assistantTurnBody: {
      version: 1,
      items: [
        { id: "tool-1", kind: "tool_call", toolCallId: "call-edit-1" },
        { id: "text-1", kind: "text", text: "Checking the current time.\n" },
        { id: "tool-2", kind: "tool_call", toolCallId: "call-time" },
        { id: "tool-3", kind: "tool_call", toolCallId: "call-edit-2" },
      ],
    },
    toolCalls: [
      {
        id: "call-edit-1",
        name: "file",
        args: JSON.stringify({ operation: "edit", path: "a.md" }),
        surface: "rich_result",
        status: "done",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited a.md",
          path: "a.md",
          diff_stats: { additions: 1, deletions: 1 },
        },
        envelope: {
          content_type: "application/vnd.spindrel.diff+text",
          body: "@@ -1 +1 @@\n-old-a\n+new-a",
          plain_body: "Edited a.md",
          display: "inline",
          truncated: false,
          record_id: "result-a",
          byte_size: 24,
        },
      },
      {
        id: "call-time",
        name: "get_current_local_time",
        surface: "transcript",
        status: "done",
        summary: {
          kind: "result",
          subject_type: "generic",
          label: "Got current local time",
          preview_text: "2026-04-22 14:05 EDT",
        },
        envelope: {
          content_type: "text/plain",
          body: "2026-04-22 14:05 EDT",
          plain_body: "2026-04-22 14:05 EDT",
          display: "badge",
          truncated: false,
          record_id: "result-time",
          byte_size: 20,
        },
      },
      {
        id: "call-edit-2",
        name: "file",
        args: JSON.stringify({ operation: "edit", path: "b.md" }),
        surface: "rich_result",
        status: "done",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited b.md",
          path: "b.md",
          diff_stats: { additions: 2, deletions: 1 },
        },
        envelope: {
          content_type: "application/vnd.spindrel.diff+text",
          body: "@@ -1 +2 @@\n-old-b\n+new-b\n+tail",
          plain_body: "Edited b.md",
          display: "inline",
          truncated: false,
          record_id: "result-b",
          byte_size: 30,
        },
      },
    ],
  });

  assert.deepEqual(
    items.map((item) => item.kind),
    ["rich_result", "text", "transcript", "rich_result"],
  );
  assert.equal(items[1]?.kind, "text");
  assert.equal(items[1]?.text, "Checking the current time.\n");
  assert.equal(items[2]?.kind, "transcript");
  if (items[2]?.kind !== "transcript") throw new Error("expected transcript item");
  assert.equal(items[2].entries[0]?.label, "Got current local time");
  assert.equal(items[2].entries[0]?.previewText, "2026-04-22 14:05 EDT");
});

test("skill load results preserve useful preview text", () => {
  const items = buildAssistantTurnBodyItems({
    assistantTurnBody: {
      version: 1,
      items: [{ id: "tool-1", kind: "tool_call", toolCallId: "call-skill" }],
    },
    toolCalls: [
      {
        id: "call-skill",
        name: "load_skill",
        args: JSON.stringify({ skill_id: "workspace_files" }),
        surface: "transcript",
        status: "done",
        summary: {
          kind: "read",
          subject_type: "skill",
          label: "Loaded skill",
          target_id: "workspace_files",
          target_label: "workspace_files/INDEX.md",
          preview_text: "# Workspace Files",
        },
        envelope: {
          content_type: "text/markdown",
          body: "# Workspace Files\n\nUse this skill to inspect the workspace.",
          plain_body: "# Workspace Files",
          display: "inline",
          truncated: false,
          record_id: "skill-1",
          byte_size: 58,
        },
      },
    ],
  });

  assert.equal(items[0]?.kind, "transcript");
  if (items[0]?.kind !== "transcript") throw new Error("expected transcript item");
  assert.equal(items[0].entries[0]?.metaLabel, "(workspace_files/INDEX.md)");
  assert.equal(items[0].entries[0]?.previewText, "# Workspace Files");
  assert.equal(items[0].entries[0]?.detailKind, "expandable");
});

test("diff results stay rich inline in the canonical builder", () => {
  const items = buildAssistantTurnBodyItems({
    assistantTurnBody: {
      version: 1,
      items: [{ id: "tool-1", kind: "tool_call", toolCallId: "call-edit" }],
    },
    toolCalls: [
      {
        id: "call-edit",
        name: "file",
        args: JSON.stringify({ operation: "edit", path: "notes.md" }),
        surface: "rich_result",
        status: "done",
        summary: {
          kind: "diff",
          subject_type: "file",
          label: "Edited notes.md",
          path: "notes.md",
          diff_stats: { additions: 1, deletions: 1 },
        },
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

  assert.equal(items[0]?.kind, "rich_result");
  if (items[0]?.kind !== "rich_result") throw new Error("expected rich_result item");
  assert.equal(items[0].envelope.content_type, "application/vnd.spindrel.diff+text");
});

test("live and persisted tool calls render identically through the canonical builder", () => {
  const assistantTurnBody = {
    version: 1 as const,
    items: [
      { id: "tool-time", kind: "tool_call" as const, toolCallId: "call-time" },
      { id: "text-1", kind: "text" as const, text: "Done.\n" },
    ],
  };

  const liveItems = buildAssistantTurnBodyItems({
    assistantTurnBody,
    toolCalls: [
      {
        id: "call-time",
        name: "get_current_local_time",
        args: "{}",
        surface: "transcript",
        status: "done",
        summary: {
          kind: "result",
          subject_type: "generic",
          label: "Got current local time",
          preview_text: "2026-04-22 14:05 EDT",
        },
        envelope: {
          content_type: "text/plain",
          body: "2026-04-22 14:05 EDT",
          plain_body: "2026-04-22 14:05 EDT",
          display: "badge",
          truncated: false,
          record_id: "result-time",
          byte_size: 20,
        },
      },
    ],
  });
  const persistedItems = buildAssistantTurnBodyItems({
    assistantTurnBody,
    toolCalls: [
      {
        id: "call-time",
        name: "get_current_local_time",
        arguments: "{}",
        surface: "transcript",
        summary: {
          kind: "result",
          subject_type: "generic",
          label: "Got current local time",
          preview_text: "2026-04-22 14:05 EDT",
        },
      },
    ],
    toolResults: [
      {
        content_type: "text/plain",
        body: "2026-04-22 14:05 EDT",
        plain_body: "2026-04-22 14:05 EDT",
        display: "badge",
        truncated: false,
        record_id: "result-time",
        byte_size: 20,
      },
    ],
  });

  const normalize = (items: ReturnType<typeof buildAssistantTurnBodyItems>) =>
    items.map((item) => {
      if (item.kind === "text") {
        return { kind: item.kind, text: item.text };
      }
      if (item.kind === "transcript") {
        return {
          kind: item.kind,
          entries: item.entries.map((entry) => ({
            kind: entry.kind,
            label: entry.label,
            metaLabel: entry.metaLabel,
            previewText: entry.previewText,
            detailKind: entry.detailKind,
            tone: entry.tone,
          })),
        };
      }
      if (item.kind === "widget") {
        return {
          kind: item.kind,
          recordId: item.widget.recordId,
          toolName: item.widget.toolName,
        };
      }
      return {
        kind: item.kind,
        contentType: item.envelope.content_type,
        recordId: item.envelope.record_id,
      };
    });

  assert.deepEqual(normalize(persistedItems), normalize(liveItems));
});

test("canonical tool surfaces are not re-inferred from envelopes", () => {
  const items = buildAssistantTurnBodyItems({
    assistantTurnBody: {
      version: 1,
      items: [{ id: "tool-1", kind: "tool_call", toolCallId: "call-edit" }],
    },
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

  assert.equal(items[0]?.kind, "transcript");
  if (items[0]?.kind !== "transcript") throw new Error("expected transcript item");
  assert.equal(items[0].entries[0]?.label, "Edited notes.md");
});

test("legacy persisted rows adapt once into the canonical assistant turn body", () => {
  const body = buildLegacyAssistantTurnBody({
    displayContent: "Done.\n",
    transcriptEntries: [
      { id: "tool-1", kind: "tool_call", toolCallId: "call-edit" },
      { id: "text-1", kind: "text", text: "Done.\n" },
    ],
    toolCalls: [
      {
        id: "call-edit",
        name: "file",
        arguments: JSON.stringify({ operation: "edit", path: "notes.md" }),
      },
    ],
  });

  assert.deepEqual(body, {
    version: 1,
    items: [
      { id: "tool-1", kind: "tool_call", toolCallId: "call-edit" },
      { id: "text-1", kind: "text", text: "Done.\n" },
    ],
  });
});

test("legacy adapter falls back to message text followed by tool rows when no transcript metadata exists", () => {
  const body = buildLegacyAssistantTurnBody({
    displayContent: "Done.\n",
    toolCalls: [
      {
        id: "call-time",
        name: "get_current_local_time",
        arguments: "{}",
      },
    ],
  });

  assert.deepEqual(body, {
    version: 1,
    items: [
      { id: "legacy:text", kind: "text", text: "Done.\n" },
      { id: "legacy:tool:call-time", kind: "tool_call", toolCallId: "call-time" },
    ],
  });
});
