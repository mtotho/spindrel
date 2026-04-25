import test from "node:test";
import assert from "node:assert/strict";

import {
  adminMachineEnrollPath,
  adminMachineProfilePath,
  adminMachineProfilesPath,
  adminMachineTargetPath,
  adminMachineTargetSetupPath,
  adminMachinesPath,
  sessionMachineTargetLeasePath,
  sessionMachineTargetPath,
} from "./machineControlApiPaths.ts";

test("machine-control admin endpoints use the api/v1 namespace", () => {
  assert.equal(adminMachinesPath(), "/api/v1/admin/machines");
  assert.equal(
    adminMachineEnrollPath("local_companion"),
    "/api/v1/admin/machines/providers/local_companion/enroll",
  );
  assert.equal(
    adminMachineTargetPath("local_companion", "desk mac"),
    "/api/v1/admin/machines/providers/local_companion/targets/desk%20mac",
  );
  assert.equal(
    adminMachineTargetSetupPath("local_companion", "desk mac"),
    "/api/v1/admin/machines/providers/local_companion/targets/desk%20mac/setup",
  );
  assert.equal(
    adminMachineProfilesPath("ssh"),
    "/api/v1/admin/machines/providers/ssh/profiles",
  );
  assert.equal(
    adminMachineProfilePath("ssh", "profile 1"),
    "/api/v1/admin/machines/providers/ssh/profiles/profile%201",
  );
});

test("machine-control session endpoints use the api/v1 namespace", () => {
  assert.equal(sessionMachineTargetPath("session-123"), "/api/v1/sessions/session-123/machine-target");
  assert.equal(
    sessionMachineTargetLeasePath("session-123"),
    "/api/v1/sessions/session-123/machine-target/lease",
  );
});
