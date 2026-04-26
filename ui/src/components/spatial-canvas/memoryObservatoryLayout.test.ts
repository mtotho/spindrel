import assert from "node:assert/strict";
import test from "node:test";
import {
  buildObservatoryEventMarks,
  buildObservatoryLanes,
  memoryFileKey,
  observatoryHorizonDays,
  temporalAgeFactor,
  temporalLaneScale,
} from "./memoryObservatoryLayout.ts";

test("memoryFileKey joins bot and file identities", () => {
  assert.equal(memoryFileKey("bot-a", "memory/a.md"), "bot-a:memory/a.md");
});

test("observatoryHorizonDays preserves the 48h window", () => {
  assert.equal(observatoryHorizonDays(2), 2);
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
  ], 8, 30, Date.parse("2026-04-26T00:00:00Z"));

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
  ], 1, 30, Date.parse("2026-04-26T00:00:00Z"));
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
  ], lanes, 30, Date.parse("2026-04-26T00:00:00Z"));

  assert.equal(marks[0].matchKey, "bot-a:memory/a.md");
  assert.ok(marks[0].r > 4);
});

test("observatory temporal helpers place recent activity closer to the core", () => {
  const now = Date.parse("2026-04-26T00:00:00Z");
  const recent = temporalAgeFactor("2026-04-25T00:00:00Z", 30, now);
  const older = temporalAgeFactor("2026-03-27T00:00:00Z", 30, now);

  assert.ok(recent < older);
  assert.ok(temporalLaneScale(recent) < temporalLaneScale(older));
});

test("buildObservatoryLanes uses file recency as radial distance", () => {
  const now = Date.parse("2026-04-26T00:00:00Z");
  const lanes = buildObservatoryLanes([
    {
      bot_id: "bot-a",
      bot_name: "Bot A",
      write_count: 2,
      last_updated_at: "2026-04-26T00:00:00Z",
      hot_files: [
        {
          id: "bot-a:memory/recent.md",
          bot_id: "bot-a",
          bot_name: "Bot A",
          file_path: "memory/recent.md",
          write_count: 1,
          hygiene_count: 0,
          last_operation: "append",
          last_updated_at: "2026-04-25T00:00:00Z",
        },
        {
          id: "bot-a:memory/older.md",
          bot_id: "bot-a",
          bot_name: "Bot A",
          file_path: "memory/older.md",
          write_count: 1,
          hygiene_count: 0,
          last_operation: "append",
          last_updated_at: "2026-03-27T00:00:00Z",
        },
      ],
    },
  ], 1, 30, now);

  const [recent, older] = lanes[0].files;
  assert.ok(Math.hypot(recent.x, recent.y) < Math.hypot(older.x, older.y));
});
