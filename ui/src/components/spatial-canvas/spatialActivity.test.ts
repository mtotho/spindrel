import test from "node:test";
import assert from "node:assert/strict";

import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import {
  formatTimeUntil,
  upcomingOrbit,
  upcomingOrbitBucket,
  upcomingHref,
  upcomingIdentityKey,
  upcomingTypeLabel,
  channelScheduleSatellites,
  scheduleSatelliteState,
} from "./spatialActivity.ts";

const base: UpcomingItem = {
  type: "heartbeat",
  scheduled_at: "2026-04-25T12:00:00.000Z",
  bot_id: "bot-a",
  bot_name: "Bot A",
  channel_id: "channel-a",
  channel_name: "Channel A",
  title: "Heartbeat",
};

test("upcoming presentation helpers centralize labels and hrefs", () => {
  assert.equal(upcomingIdentityKey(base), "heartbeat:channel-a");
  assert.equal(upcomingHref(base), "/channels/channel-a/settings#automation");
  assert.equal(upcomingTypeLabel({ ...base, type: "memory_hygiene", channel_id: null }), "dreaming");
  assert.equal(
    upcomingHref({ ...base, type: "task", task_id: "task-a" }),
    "/admin/automations/task-a",
  );
});

test("formatTimeUntil is forward-looking and stable around now", () => {
  const now = Date.parse("2026-04-25T12:00:00.000Z");
  assert.equal(formatTimeUntil("2026-04-25T12:00:30.000Z", now), "now");
  assert.equal(formatTimeUntil("2026-04-25T12:05:00.000Z", now), "in 5m");
  assert.equal(formatTimeUntil("2026-04-25T14:00:00.000Z", now), "in 2h");
  assert.equal(formatTimeUntil("2026-04-25T11:00:00.000Z", now), "due");
});

test("upcoming orbit spread is deterministic and leaves single items on base orbit", () => {
  const now = Date.parse("2026-04-25T11:00:00.000Z");
  const baseOrbit = upcomingOrbit(base, now);
  const singleSpread = upcomingOrbit(base, now, { index: 0, count: 1 });
  const firstSpread = upcomingOrbit(base, now, { index: 0, count: 3 });
  const secondSpread = upcomingOrbit(base, now, { index: 1, count: 3 });
  const thirdSpread = upcomingOrbit(base, now, { index: 2, count: 3 });

  assert.deepEqual(singleSpread, baseOrbit);
  assert.deepEqual(upcomingOrbit(base, now, { index: 0, count: 3 }), firstSpread);
  assert.notEqual(firstSpread.x, secondSpread.x);
  assert.notEqual(thirdSpread.y, secondSpread.y);
  assert.equal(upcomingOrbitBucket(base, now), upcomingOrbitBucket(base, now));
});

test("channel schedule satellites keep channel-bound work local and capped", () => {
  const now = Date.parse("2026-04-25T11:00:00.000Z");
  const items: UpcomingItem[] = [
    { ...base, scheduled_at: "2026-04-25T11:10:00.000Z" },
    { ...base, type: "task", task_id: "task-a", title: "QA sweep", scheduled_at: "2026-04-25T13:00:00.000Z" },
    { ...base, type: "task", task_id: "task-b", title: "Second task", scheduled_at: "2026-04-25T14:00:00.000Z" },
    { ...base, type: "task", task_id: "task-c", title: "Hidden task", scheduled_at: "2026-04-25T15:00:00.000Z" },
    { ...base, type: "memory_hygiene", channel_id: null, title: "Dreaming" },
  ];

  const layout = channelScheduleSatellites(
    items,
    [{ channelId: "channel-a", nodeId: "node-a", x: 100, y: 200, w: 220, h: 140 }],
    now,
    3,
  );

  assert.equal(layout.satellites.length, 3);
  assert.equal(layout.overflow.length, 1);
  assert.equal(layout.overflow[0].count, 1);
  assert.equal(layout.satellites[0].item.title, "Heartbeat");
  assert.equal(layout.satellites[0].state, "imminent");
  assert.equal(layout.satellites[0].anchorX, 210);
  assert.equal(layout.satellites[0].anchorY, 270);
  assert.ok(layout.satellites.every((sat) => sat.channelId === "channel-a"));
  assert.ok(layout.satellites.every((sat) => Math.hypot(sat.x - sat.anchorX, sat.y - sat.anchorY) > 80));
});

test("schedule satellite state distinguishes due, imminent, soon, and normal", () => {
  const now = Date.parse("2026-04-25T11:00:00.000Z");
  assert.equal(scheduleSatelliteState("2026-04-25T10:59:00.000Z", now).state, "due");
  assert.equal(scheduleSatelliteState("2026-04-25T11:10:00.000Z", now).state, "imminent");
  assert.equal(scheduleSatelliteState("2026-04-25T11:30:00.000Z", now).state, "soon");
  assert.equal(scheduleSatelliteState("2026-04-25T13:00:00.000Z", now).state, "normal");
});
