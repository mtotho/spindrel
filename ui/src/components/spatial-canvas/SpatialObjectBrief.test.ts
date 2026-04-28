import assert from "node:assert/strict";
import test from "node:test";
import { buildSpatialObjectBrief } from "./SpatialObjectBrief.js";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";

const base: WorkspaceMapObjectState = {
  node_id: "node-1",
  kind: "channel",
  target_id: "channel-1",
  label: "Quality",
  status: "idle",
  severity: null,
  primary_signal: null,
  secondary_signal: null,
  counts: { upcoming: 0, recent: 0, warnings: 0, widgets: 0, integrations: 0, bots: 1 },
  next: null,
  recent: [],
  warnings: [],
  source: { primary_bot_name: "Rolland" },
  attached: { heartbeat: { enabled: true, interval_minutes: 30 } },
};

test("buildSpatialObjectBrief explains quiet channel source state", () => {
  const brief = buildSpatialObjectBrief(base, Date.parse("2026-04-28T12:00:00Z"));
  assert.equal(brief?.headline, "Quiet");
  assert.equal(brief?.summary, "No scheduled work or recent warnings on this object.");
  assert.deepEqual(brief?.sourceLines, ["Primary bot: Rolland", "Heartbeat enabled, every 30m"]);
});

test("buildSpatialObjectBrief prioritizes warnings for error objects", () => {
  const brief = buildSpatialObjectBrief(
    {
      ...base,
      status: "error",
      severity: "error",
      primary_signal: "Trace error",
      counts: { ...base.counts, recent: 1, warnings: 1 },
      warnings: [
        {
          kind: "trace",
          title: "mermaid_to_excalidraw failed",
          severity: "error",
          created_at: "2026-04-28T11:55:00Z",
        },
      ],
      recent: [
        {
          kind: "trace",
          title: "mermaid_to_excalidraw failed",
          status: "error",
          created_at: "2026-04-28T11:55:00Z",
        },
      ],
    },
    Date.parse("2026-04-28T12:00:00Z"),
  );
  assert.equal(brief?.tone, "danger");
  assert.equal(brief?.headline, "mermaid_to_excalidraw failed");
  assert.match(brief?.summary ?? "", /1 warning/);
  assert.equal(brief?.recent.length, 0);
});

test("buildSpatialObjectBrief dedupes repeated recent signals", () => {
  const signal = {
    kind: "task",
    title: "Heartbeat",
    task_id: "task-1",
    bot_id: "bot-1",
    created_at: "2026-04-28T11:50:00Z",
  };
  const brief = buildSpatialObjectBrief(
    {
      ...base,
      status: "recent",
      counts: { ...base.counts, recent: 2 },
      recent: [signal, { ...signal }],
    },
    Date.parse("2026-04-28T12:00:00Z"),
  );
  assert.equal(brief?.recent.length, 1);
  assert.match(brief?.summary ?? "", /Recent: Heartbeat/);
});
