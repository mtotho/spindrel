import assert from "node:assert/strict";
import test from "node:test";
import {
  buildObservatoryEventMarks,
  buildObservatoryLanes,
  memoryFileKey,
} from "./memoryObservatoryLayout.ts";

test("memoryFileKey joins bot and file identities", () => {
  assert.equal(memoryFileKey("bot-a", "memory/a.md"), "bot-a:memory/a.md");
});

test("buildObservatoryLanes sizes hot file bodies by write count", () => {
  const lanes = buildObservatoryLanes([
    {
      bot_id: "bot-a",
      bot_name: "Bot A",
      write_count: 8,
      last_updated_at: "2026-04-26T00:00:00Z",
      hot_files: [
        {
          id: "bot-a:memory/hot.md",
          bot_id: "bot-a",
          bot_name: "Bot A",
          file_path: "memory/hot.md",
          write_count: 8,
          hygiene_count: 2,
          last_operation: "append",
          last_updated_at: "2026-04-26T00:00:00Z",
        },
        {
          id: "bot-a:memory/cool.md",
          bot_id: "bot-a",
          bot_name: "Bot A",
          file_path: "memory/cool.md",
          write_count: 1,
          hygiene_count: 0,
          last_operation: "write",
          last_updated_at: "2026-04-26T00:00:00Z",
        },
      ],
    },
  ], 8);

  assert.equal(lanes.length, 1);
  assert.equal(lanes[0].files.length, 2);
  assert.ok(lanes[0].files[0].r > lanes[0].files[1].r);
});

test("buildObservatoryEventMarks preserves file match keys", () => {
  const lanes = buildObservatoryLanes([
    {
      bot_id: "bot-a",
      bot_name: "Bot A",
      write_count: 1,
      hot_files: [],
      last_updated_at: "2026-04-26T00:00:00Z",
    },
  ], 1);
  const marks = buildObservatoryEventMarks([
    {
      bot_id: "bot-a",
      bot_name: "Bot A",
      file_path: "memory/a.md",
      operation: "append",
      created_at: "2026-04-26T00:00:00Z",
      is_hygiene: true,
      correlation_id: "run-1",
      job_type: "memory_hygiene",
    },
  ], lanes);

  assert.equal(marks[0].matchKey, "bot-a:memory/a.md");
  assert.ok(marks[0].r > 4);
});
