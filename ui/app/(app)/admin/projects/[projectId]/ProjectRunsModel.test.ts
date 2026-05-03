import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BOARD_COLUMNS,
  buildBoardItems,
  buildFeedItems,
  groupBoardColumns,
  sortScheduleRailItems,
} from "./ProjectRunsModel.js";
import type {
  ProjectCodingRun,
  ProjectCodingRunSchedule,
} from "@/src/types/api";

function run(overrides: Partial<ProjectCodingRun>): ProjectCodingRun {
  const id = overrides.id ?? "run-1";
  return {
    id,
    project_id: "project-1",
    status: "complete",
    request: "",
    repo: {},
    runtime_target: {},
    dev_targets: [],
    dependency_stack: {},
    execution_environment: {},
    readiness: {},
    work_surface: {},
    continuation_index: 0,
    continuation_count: 0,
    continuations: [],
    loop: {},
    lifecycle: {},
    activity: [],
    review: {},
    task: {
      id: `${id}-task`,
      status: overrides.status ?? "complete",
      title: "Project coding run",
      bot_id: "agent",
    },
    created_at: "2026-05-01T12:00:00Z",
    updated_at: "2026-05-01T12:00:00Z",
    ...overrides,
  } as ProjectCodingRun;
}

function schedule(overrides: Partial<ProjectCodingRunSchedule>): ProjectCodingRunSchedule {
  return {
    id: overrides.id ?? "schedule-1",
    project_id: "project-1",
    title: "Schedule",
    status: "active",
    enabled: true,
    run_count: 0,
    ...overrides,
  };
}

describe("Project Runs model", () => {
  it("keeps scheduled work in a rail and out of board columns", () => {
    assert.deepEqual(BOARD_COLUMNS, ["backlog", "running", "review", "closed"]);
    const boardItems = buildBoardItems({
      runs: [run({ id: "closed", status: "complete" })],
      reviewBatches: [],
      reviewSessions: [],
      inboxItems: [],
    });
    const columns = groupBoardColumns(boardItems);

    assert.equal(columns.backlog[0]?.kind, "new_run");
    assert.equal(columns.closed.length, 1);
    assert.equal(Object.keys(columns).includes("scheduled"), false);
  });

  it("orders the schedule rail with launcher, soonest active schedules, manual, then paused", () => {
    const rail = sortScheduleRailItems([
      schedule({ id: "manual", title: "Manual", scheduled_at: null, recurrence: null }),
      schedule({ id: "later", title: "Later", scheduled_at: "2026-05-04T15:00:00Z", recurrence: "+1w" }),
      schedule({ id: "soon", title: "Soon", scheduled_at: "2026-05-04T10:00:00Z", recurrence: "+1d" }),
      schedule({ id: "paused", title: "Paused", enabled: false, status: "cancelled", scheduled_at: "2026-05-04T09:00:00Z" }),
    ]);

    assert.deepEqual(rail.map((item) => item.id), [
      "action:new-schedule",
      "schedule:soon",
      "schedule:later",
      "schedule:manual",
      "schedule:paused",
    ]);
  });

  it("builds a chronological feed with upcoming schedules, active runs, then history", () => {
    const feed = buildFeedItems({
      schedules: [
        schedule({ id: "upcoming-later", scheduled_at: "2026-05-05T10:00:00Z" }),
        schedule({ id: "upcoming-soon", scheduled_at: "2026-05-04T10:00:00Z" }),
      ],
      runs: [
        run({ id: "history", status: "complete", updated_at: "2026-05-01T10:00:00Z" }),
        run({ id: "active", status: "running", updated_at: "2026-05-03T10:00:00Z", task: { id: "active-task", status: "running", title: "Active", bot_id: "agent" } }),
      ],
    });

    assert.deepEqual(feed.map((item) => item.id), [
      "schedule:upcoming-soon",
      "schedule:upcoming-later",
      "run:active",
      "run:history",
    ]);
    assert.deepEqual(feed.map((item) => item.group), ["upcoming", "upcoming", "active", "history"]);
  });
});
