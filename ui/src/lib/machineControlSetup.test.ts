import test from "node:test";
import assert from "node:assert/strict";

import { buildRemoteEnrollCommand, resolveMachineControlServerUrl } from "./machineControlSetup.ts";

test("resolveMachineControlServerUrl trims trailing slash noise", () => {
  assert.equal(resolveMachineControlServerUrl("https://spindrel.local///"), "https://spindrel.local");
  assert.equal(resolveMachineControlServerUrl(""), "");
});

test("buildRemoteEnrollCommand emits a ready-to-run enroll curl with optional label", () => {
  const command = buildRemoteEnrollCommand({
    serverUrl: "https://spindrel.local/",
    providerId: "local_companion",
    apiKey: "sp_test_123",
    label: "Desk Mac",
    config: { host: "10.0.0.8", username: "matt" },
  });

  assert.match(command, /Authorization: Bearer sp_test_123/);
  assert.match(command, /\/api\/v1\/admin\/machines\/providers\/local_companion\/enroll/);
  assert.match(command, /-d '\{"label":"Desk Mac","config":\{"host":"10\.0\.0\.8","username":"matt"\}\}'/);
});

test("buildRemoteEnrollCommand shell-escapes apostrophes in labels", () => {
  const command = buildRemoteEnrollCommand({
    serverUrl: "https://spindrel.local/",
    providerId: "local_companion",
    apiKey: "sp_test_123",
    label: "Matt's Mac",
  });

  assert.match(command, /Matt'"'"'s Mac/);
});
