import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ADMIN_MACHINES_SOURCE = readFileSync(
  resolve(process.cwd(), "app/(app)/admin/machines/index.tsx"),
  "utf8",
);

test("machine profile setup guide is available while creating and editing", () => {
  assert.match(ADMIN_MACHINES_SOURCE, /provider\.profile_setup_guide\s*&&\s*\(/);
  assert.doesNotMatch(ADMIN_MACHINES_SOURCE, /!editingProfile\s*&&\s*provider\.profile_setup_guide/);
});

test("machine profiles expose an explicit add path after profiles exist", () => {
  assert.match(ADMIN_MACHINES_SOURCE, /function handleStartCreateProfile\(\)/);
  assert.match(ADMIN_MACHINES_SOURCE, /label="Add profile"/);
  assert.match(ADMIN_MACHINES_SOURCE, /onPress=\{handleStartCreateProfile\}/);
});

test("machine profile delete clicks are never silently swallowed for bound profiles", () => {
  assert.match(ADMIN_MACHINES_SOURCE, /Profile still in use/);
  assert.match(ADMIN_MACHINES_SOURCE, /Remove or reassign those targets before deleting the profile/);
  assert.doesNotMatch(ADMIN_MACHINES_SOURCE, /disabled=\{pending \|\| profile\.target_count > 0\}/);
});
